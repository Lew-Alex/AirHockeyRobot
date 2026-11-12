import com.example.fastcam.PuckCoordinateServer
import java.net.Socket
import java.nio.charset.StandardCharsets

/**
 * Standalone JVM socket smoke test. Compile with PuckCoordinateServer.kt and run this main class.
 * Example: kotlinc app/src/main/java/com/example/fastcam/PuckCoordinateServer.kt tools/PuckCoordinateServerIntegrationTest.kt -include-runtime -d puck-server-test.jar
 */
object PuckCoordinateServerIntegrationTest {
    @JvmStatic
    fun main(args: Array<String>) {
        val errors = mutableListOf<String>()
        val server = PuckCoordinateServer { synchronized(errors) { errors.add(it) } }

        try {
            server.start()
            SocketLoopback.connect().use { socket ->
                socket.soTimeout = 2_000
                expectPublishedLine(server, socket, "{\"x\":12.5,\"y\":-3}")
            }

            // Exercise a rapid stop/start and verify the new listener can accept and stream.
            server.stop()
            server.start()
            SocketLoopback.connect().use { socket ->
                socket.soTimeout = 2_000
                expectPublishedLine(server, socket, "{\"x\":0,\"y\":1}")
            }

            check(synchronized(errors) { errors.isEmpty() }) { "Unexpected server errors: $errors" }
            println("PuckCoordinateServer integration test passed")
        } finally {
            server.stop()
        }
    }

    private fun expectPublishedLine(server: PuckCoordinateServer, socket: Socket, expected: String) {
        val input = socket.getInputStream()
        val reader = input.bufferedReader(StandardCharsets.UTF_8)
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
