import com.example.fastcam.PuckCoordinateServer
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicLong

/**
 * Standalone JVM socket smoke test. Compile with PuckCoordinateServer.kt and run this main class.
 * Example: kotlinc app/src/main/java/com/example/fastcam/PuckCoordinateServer.kt tools/PuckCoordinateServerIntegrationTest.kt -include-runtime -d puck-server-test.jar
 */
object PuckCoordinateServerIntegrationTest {
    @JvmStatic
    fun main(args: Array<String>) {
        val errors = mutableListOf<String>()
        val testClock = AtomicLong(100)
        val server = PuckCoordinateServer(
            clockNs = { testClock.incrementAndGet() },
            clockName = "test_clock"
        ) { synchronized(errors) { errors.add(it) } }
        var firstRun: PuckCoordinateServer.Snapshot? = null

        try {
            check(server.snapshot() == PuckCoordinateServer.Snapshot(0, 0, 0, 0, 0.0, 0.0))
            server.start()
            SocketLoopback.connect().use { socket ->
                socket.soTimeout = 2_000
                val reader = socket.getInputStream().bufferedReader(StandardCharsets.UTF_8)
                socket.getOutputStream().write("CLOCK_SYNC sync_1\n".toByteArray(StandardCharsets.US_ASCII))
                val syncReply = reader.readLine()
                check(syncReply == "{\"type\":\"clock_sync\",\"id\":\"sync_1\",\"phone_receive_ns\":101," +
                    "\"phone_send_ns\":102,\"clock\":\"test_clock\"}") {
                    "Unexpected clock sync reply: $syncReply"
                }
                val afterSync = server.snapshot()
                check(afterSync.offeredMessages == 0L && afterSync.writtenMessages == 0L) {
                    "Clock replies must not change coordinate counters: $afterSync"
                }
                expectPublishedLine(server, socket, reader, "{\"x\":12.5,\"y\":-3}")
                awaitWrittenMessage(server)
                firstRun = server.snapshot()
                check(firstRun!!.clients == 1) { "Expected one live client, got $firstRun" }
            }
            val completedFirstRun = checkNotNull(firstRun)
            check(completedFirstRun.offeredMessages >= 1) { "Expected an offer counter, got $completedFirstRun" }
            check(completedFirstRun.writtenMessages >= 1) { "Expected a write counter, got $completedFirstRun" }
            check(completedFirstRun.offeredMessages >= completedFirstRun.writtenMessages)
            check(completedFirstRun.replacedMessages >= 0)
            check(completedFirstRun.lastWriteMs >= 0.0 && completedFirstRun.maxWriteMs >= completedFirstRun.lastWriteMs) {
                "Invalid write timings: $completedFirstRun"
            }

            // Exercise a rapid stop/start and verify the new listener can accept and stream.
            server.stop()
            check(server.snapshot().offeredMessages == completedFirstRun.offeredMessages) {
                "Stopped-run counters should remain visible until the next start"
            }
            server.start()
            check(server.snapshot().offeredMessages == 0L && server.snapshot().writtenMessages == 0L) {
                "Counters should reset when a new server run starts"
            }
            SocketLoopback.connect().use { socket ->
                socket.soTimeout = 2_000
                val reader = socket.getInputStream().bufferedReader(StandardCharsets.UTF_8)
                expectPublishedLine(server, socket, reader, "{\"x\":0,\"y\":1}")
                awaitWrittenMessage(server)
            }
            val secondRun = server.snapshot()
            check(secondRun.offeredMessages >= 1 && secondRun.writtenMessages >= 1) {
                "Expected counters for the new run, got $secondRun"
            }

            check(synchronized(errors) { errors.isEmpty() }) { "Unexpected server errors: $errors" }
            println("PuckCoordinateServer integration test passed")
        } finally {
            server.stop()
        }
    }

    private fun expectPublishedLine(
        server: PuckCoordinateServer,
        socket: Socket,
        reader: java.io.BufferedReader,
        expected: String
    ) {
        val input = socket.getInputStream()
        val deadline = System.nanoTime() + 2_000_000_000L
        while (input.available() == 0 && System.nanoTime() < deadline) {
            // Keep offering the latest state until the asynchronous accept worker registers us.
            server.publish(expected)
            Thread.sleep(10)
        }
        check(input.available() > 0) { "Timed out waiting for server output" }
        val actual = reader.readLine()
        check(actual == expected) { "Expected '$expected', received '$actual'" }
    }

    private fun awaitWrittenMessage(server: PuckCoordinateServer) {
        val deadline = System.nanoTime() + 2_000_000_000L
        while (server.snapshot().writtenMessages == 0L && System.nanoTime() < deadline) {
            Thread.sleep(5)
        }
        check(server.snapshot().writtenMessages > 0L) { "Timed out waiting for the write counter" }
    }

    private object SocketLoopback {
        fun connect(): Socket {
            var lastError: Exception? = null
            repeat(50) {
                try {
                    return Socket("127.0.0.1", PuckCoordinateServer.DEFAULT_PORT)
                } catch (e: Exception) {
                    lastError = e
                    Thread.sleep(20)
                }
            }
            throw AssertionError("Server did not accept a loopback connection", lastError)
        }
    }
}
