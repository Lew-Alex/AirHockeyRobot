package com.example.fastcam

import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Streams the latest puck-coordinate JSON object to local TCP clients as newline-delimited JSON.
 *
 * The server binds only to 127.0.0.1. For access from a host computer, forward [DEFAULT_PORT]
 * with `adb forward tcp:8765 tcp:8765`. Publishing is non-blocking: each connected client retains
 * at most its most recent pending message, so a slow reader cannot stall tracking or build a queue.
 */
class PuckCoordinateServer(
    private val onError: (String) -> Unit = {}
) {
    companion object {
        const val DEFAULT_PORT = 8765
        private const val MAX_CLIENTS = 4
        private const val MAX_MESSAGE_BYTES = 16 * 1024
        private val LOOPBACK: InetAddress = InetAddress.getByName("127.0.0.1")
    }

    private val lifecycleLock = Any()
    @Volatile private var activeRun: ServerRun? = null

    /** Starts accepting connections on a background thread. Repeated starts while running do nothing. */
    fun start() {
        synchronized(lifecycleLock) {
            if (activeRun?.isRunning == true) return
            val run = ServerRun()
            activeRun = run
            run.start()
        }
    }

    /**
     * Offers one JSON object to all connected clients. The call only encodes and replaces each
     * client's pending message; socket writes happen on per-client background workers.
     */
    fun publish(json: String) {
        if ('\n' in json || '\r' in json) {
            report("Puck coordinate message must be a single JSON line")
            return
        }
        val bytes = json.toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > MAX_MESSAGE_BYTES) {
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
        @Volatile private var serverSocket: ServerSocket? = null

        val isRunning: Boolean get() = running.get()

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
            private val pending = AtomicReference<ByteArray?>(null)
            private val signal = Object()

            fun start() {
                Thread(::writeLoop, "puck-coordinate-client").apply {
                    isDaemon = true
                    start()
                }
            }

            fun offer(bytes: ByteArray) {
                if (!open.get()) return
                pending.set(bytes)
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
                        val message = synchronized(signal) {
                            while (open.get() && running.get() && pending.get() == null) signal.wait()
                            pending.getAndSet(null)
                        } ?: continue
                        output.write(message)
                        output.write('\n'.code)
                        output.flush()
                    }
                } catch (e: IOException) {
                    if (open.get() && running.get()) report("Puck coordinate client write failed: ${e.message}")
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                } finally {
                    shutdown()
                    clients.remove(this)
                }
            }
        }
    }
}
