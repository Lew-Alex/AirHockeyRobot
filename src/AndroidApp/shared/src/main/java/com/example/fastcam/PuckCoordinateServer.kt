package com.example.fastcam

import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Streams the latest puck-coordinate JSON object to local TCP clients as newline-delimited JSON.
 *
 * The server binds only to 127.0.0.1. For access from a host computer, forward [DEFAULT_PORT]
 * with `adb forward tcp:8765 tcp:8765`. Publishing is non-blocking: each connected client retains
 * at most its most recent pending message, so a slow reader cannot stall tracking or build a queue.
 */
class PuckCoordinateServer(
    private val clockNs: () -> Long = { System.nanoTime() },
    private val clockName: String = "phone_monotonic",
    private val onError: (String) -> Unit = {}
) {
    /** Per-client aggregate counters for the current (or most recently stopped) server run. */
    data class Snapshot(
        val clients: Int,
        val offeredMessages: Long,
        val writtenMessages: Long,
        val replacedMessages: Long,
        val lastWriteMs: Double,
        val maxWriteMs: Double
    )

    private data class ClockSyncRequest(val id: String, val phoneReceiveNs: Long)
    private data class PendingWork(val clockSync: ClockSyncRequest?, val message: ByteArray?)

    companion object {
        const val DEFAULT_PORT = 8765
        private const val MAX_CLIENTS = 4
        private const val MAX_MESSAGE_BYTES = 16 * 1024
        private const val MAX_CONTROL_LINE_BYTES = 128
        private const val MAX_CLOCK_SYNC_ID_LENGTH = 64
        private const val MIN_CLOCK_SYNC_INTERVAL_NS = 50_000_000L
        private val CLOCK_SYNC_ID = Regex("[A-Za-z0-9_-]{1,$MAX_CLOCK_SYNC_ID_LENGTH}")
        private val LOOPBACK: InetAddress = InetAddress.getByName("127.0.0.1")
    }

    init {
        require(clockName.matches(Regex("[A-Za-z0-9_-]{1,32}"))) { "Invalid clock name" }
    }

    private val lifecycleLock = Any()
    @Volatile private var activeRun: ServerRun? = null
    @Volatile private var lastRun: ServerRun? = null

    /** Starts accepting connections on a background thread. Repeated starts while running do nothing. */
    fun start() {
        synchronized(lifecycleLock) {
            if (activeRun?.isRunning == true) return
            val run = ServerRun()
            lastRun = run
            activeRun = run
            run.start()
        }
    }

    /**
     * Returns best-effort transport counters without waiting for clients or socket I/O.
     * Message totals count per-client offers/writes, not unique camera frames.
     */
    fun snapshot(): Snapshot = (activeRun ?: lastRun)?.snapshot() ?: Snapshot(0, 0, 0, 0, 0.0, 0.0)

    /**
     * Offers one JSON object to all connected clients. The call only encodes and replaces each
     * client's pending message; socket writes happen on per-client background workers.
     */
    fun publish(json: String) {
        if ('\n' in json || '\r' in json) {
            report("Puck coordinate message must be a single JSON line")
            return
        }
        val bytes = (json + '\n').toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > MAX_MESSAGE_BYTES + 1) {
            report("Puck coordinate message exceeds $MAX_MESSAGE_BYTES bytes")
            return
        }
        activeRun?.publish(bytes)
    }

    /** Stops accepting clients and closes current connections. Safe to call repeatedly. */
    fun stop() {
        synchronized(lifecycleLock) {
            val previous = activeRun
            activeRun = null
            // Close the old listener before allowing start() to bind a replacement on the same port.
            previous?.shutdown()
        }
    }

    private fun report(message: String) {
        try {
            onError(message)
        } catch (_: Throwable) {
            // Error reporting must never take down the tracking or networking worker.
        }
    }

    private inner class ServerRun {
        private val running = AtomicBoolean(true)
        private val clients = ConcurrentHashMap.newKeySet<Client>()
        private val admissionLock = Any()
        private val offeredMessages = AtomicLong()
        private val writtenMessages = AtomicLong()
        private val replacedMessages = AtomicLong()
        private val lastWriteNanosBits = AtomicLong(java.lang.Double.doubleToRawLongBits(0.0))
        private val maxWriteNanosBits = AtomicLong(java.lang.Double.doubleToRawLongBits(0.0))
        @Volatile private var serverSocket: ServerSocket? = null

        val isRunning: Boolean get() = running.get()

        fun snapshot(): Snapshot = Snapshot(
            clients = clients.count { it.isOpen },
            offeredMessages = offeredMessages.get(),
            writtenMessages = writtenMessages.get(),
            replacedMessages = replacedMessages.get(),
            lastWriteMs = java.lang.Double.longBitsToDouble(lastWriteNanosBits.get()) / 1e6,
            maxWriteMs = java.lang.Double.longBitsToDouble(maxWriteNanosBits.get()) / 1e6
        )

        private fun recordWriteDuration(durationNs: Long) {
            val durationBits = java.lang.Double.doubleToRawLongBits(durationNs.toDouble())
            lastWriteNanosBits.set(durationBits)
            while (true) {
                val currentBits = maxWriteNanosBits.get()
                val currentNs = java.lang.Double.longBitsToDouble(currentBits)
                if (durationNs.toDouble() <= currentNs) return
                if (maxWriteNanosBits.compareAndSet(currentBits, durationBits)) return
            }
        }

        fun start() {
            Thread(::acceptLoop, "puck-coordinate-accept").apply {
                isDaemon = true
                start()
            }
        }

        fun publish(bytes: ByteArray) {
            if (!running.get()) return
            for (client in clients) client.offer(bytes)
        }

        fun shutdown() {
            if (!running.getAndSet(false)) return
            try {
                serverSocket?.close()
            } catch (_: IOException) {
            }
            clients.toList().forEach(Client::shutdown)
        }

        private fun acceptLoop() {
            try {
                val listener = ServerSocket()
                listener.reuseAddress = true
                synchronized(this) {
                    if (!running.get()) {
                        listener.close()
                        return
                    }
                    serverSocket = listener
                    listener.bind(java.net.InetSocketAddress(LOOPBACK, DEFAULT_PORT))
                }

                while (running.get()) {
                    val socket = listener.accept()
                    admit(socket)
                }
            } catch (e: IOException) {
                if (running.get()) report("Puck coordinate server on 127.0.0.1:$DEFAULT_PORT: ${e.message}")
            } finally {
                running.set(false)
                try { serverSocket?.close() } catch (_: IOException) {}
                clients.toList().forEach(Client::shutdown)
                synchronized(lifecycleLock) {
                    if (activeRun === this) activeRun = null
                }
            }
        }

        private fun admit(socket: Socket) {
            val accepted = synchronized(admissionLock) {
                if (running.get() && clients.size < MAX_CLIENTS) {
                    try {
                        socket.tcpNoDelay = true
                        // Hint a small kernel queue so a slow USB reader cannot hide
                        // a long backlog ahead of our latest-only application slot.
                        // The OS may round/enlarge this; it is not a latency guarantee.
                        try { socket.sendBufferSize = 4096 } catch (_: IOException) { /* optional OS hint */ }
                        Client(socket).also { clients.add(it) }
                    } catch (e: IOException) {
                        report("Could not configure puck coordinate client: ${e.message}")
                        null
                    }
                } else null
            }
            if (accepted == null) {
                try { socket.close() } catch (_: IOException) {}
            } else {
                accepted.start()
            }
        }

        private inner class Client(private val socket: Socket) {
            private val open = AtomicBoolean(true)
            val isOpen: Boolean get() = open.get()
            private val pending = AtomicReference<ByteArray?>(null)
            private val pendingClockSync = AtomicReference<ClockSyncRequest?>(null)
            private val signal = Object()
            private var lastClockSyncNs: Long? = null

            fun start() {
                Thread(::writeLoop, "puck-coordinate-client").apply {
                    isDaemon = true
                    start()
                }
                Thread(::readControlLoop, "puck-coordinate-control").apply {
                    isDaemon = true
                    start()
                }
            }

            fun offer(bytes: ByteArray) {
                if (!open.get()) return
                offeredMessages.incrementAndGet()
                if (pending.getAndSet(bytes) != null) replacedMessages.incrementAndGet()
                synchronized(signal) { signal.notify() }
            }

            fun shutdown() {
                if (!open.getAndSet(false)) return
                synchronized(signal) { signal.notifyAll() }
                try { socket.close() } catch (_: IOException) {}
            }

            private fun writeLoop() {
                try {
                    val output = socket.getOutputStream()
                    while (open.get() && running.get()) {
                        val work = synchronized(signal) {
                            while (open.get() && running.get() &&
                                pendingClockSync.get() == null && pending.get() == null) signal.wait()
                            if (!open.get() || !running.get()) null
                            else {
                                val sync = pendingClockSync.getAndSet(null)
                                if (sync != null) PendingWork(sync, null)
                                else PendingWork(null, pending.getAndSet(null))
                            }
                        } ?: continue
                        val sync = work.clockSync
                        if (sync != null) {
                            // Sample immediately before formatting and writing the response.
                            val phoneSendNs = clockNs()
                            val reply = "{\"type\":\"clock_sync\",\"id\":\"${sync.id}\"," +
                                "\"phone_receive_ns\":${sync.phoneReceiveNs},\"phone_send_ns\":$phoneSendNs," +
                                "\"clock\":\"$clockName\"}\n"
                            output.write(reply.toByteArray(StandardCharsets.UTF_8))
                            output.flush()
                        } else {
                            val message = work.message ?: continue
                            val writeStarted = System.nanoTime()
                            output.write(message)
                            output.flush()
                            recordWriteDuration(System.nanoTime() - writeStarted)
                            writtenMessages.incrementAndGet()
                        }
                    }
                } catch (_: IOException) {
                    // A laptop reader may disconnect between benchmarks. Drop that
                    // client; a per-client I/O error must not stop the camera/tracker.
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                } finally {
                    shutdown()
                    clients.remove(this)
                }
            }

            private fun readControlLoop() {
                try {
                    val input = socket.getInputStream()
                    val line = ByteArray(MAX_CONTROL_LINE_BYTES)
                    var length = 0
                    while (open.get() && running.get()) {
                        val byte = input.read()
                        if (byte < 0) return
                        if (byte == '\n'.code) {
                            val phoneReceiveNs = clockNs()
                            var contentLength = length
                            if (contentLength > 0 && line[contentLength - 1] == '\r'.code.toByte()) contentLength--
                            val text = String(line, 0, contentLength, StandardCharsets.US_ASCII)
                            length = 0
                            handleControlLine(text, phoneReceiveNs)
                        } else {
                            if (length == line.size) {
                                shutdown()
                                return
                            }
                            line[length++] = byte.toByte()
                        }
                    }
                } catch (_: IOException) {
                    shutdown() // isolate a failed client instead of reporting a fatal server error
                } finally {
                    // A normal client half-close can still receive its pending reply; writer
                    // lifetime remains tied to socket writes or server shutdown.
                }
            }

            private fun handleControlLine(line: String, phoneReceiveNs: Long) {
                if (!line.startsWith("CLOCK_SYNC ")) return
                val id = line.removePrefix("CLOCK_SYNC ")
                if (!CLOCK_SYNC_ID.matches(id)) return
                val previous = lastClockSyncNs
                if (previous != null && phoneReceiveNs - previous < MIN_CLOCK_SYNC_INTERVAL_NS) return
                lastClockSyncNs = phoneReceiveNs
                pendingClockSync.set(ClockSyncRequest(id, phoneReceiveNs))
                synchronized(signal) { signal.notify() }
            }
        }
    }
}
