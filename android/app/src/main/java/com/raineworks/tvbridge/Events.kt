package com.raineworks.tvbridge

import android.util.Log
import org.json.JSONObject
import java.io.InputStream
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * What happens on the TV, for Home Assistant (GET /api/events): a stream of
 * JSON events, one a line, as they happen. A ping every [PING_S] seconds
 * keeps the connection known alive; the first event is a hello with this
 * run of the app.
 */
object Events {
    private const val TAG = "TvBridge"
    private const val PING_S = 15L
    private const val MAX_STREAMS = 4
    private const val MAX_QUEUED = 256
    private val CLOSED = ByteArray(0)

    private val streams = CopyOnWriteArrayList<Stream>()

    /** Sends [type] (with [data]) to every connected Home Assistant. */
    fun emit(type: String, data: JSONObject = JSONObject()) {
        val line = data.put("type", type).put("time", System.currentTimeMillis()).toString() + "\n"
        val bytes = line.toByteArray(Charsets.UTF_8)
        streams.forEach { it.offer(bytes) }
        Log.d(TAG, "Event: $line")
    }

    /** A new connection's stream; the oldest goes when there are too many. */
    fun open(): InputStream {
        while (streams.size >= MAX_STREAMS) streams.firstOrNull()?.let { it.end(); streams.remove(it) }
        return Stream().also {
            streams.add(it)
            it.offer(
                (JSONObject().put("type", "hello").put("instance", Notifier.instance).put("app_version", BuildConfig.VERSION_NAME)
                    .put("time", System.currentTimeMillis()).toString() + "\n").toByteArray(Charsets.UTF_8),
            )
        }
    }

    /** Lines handed to the HTTP server as it asks for them (it blocks in read until there's one). */
    private class Stream : InputStream() {
        private val queue = LinkedBlockingQueue<ByteArray>(MAX_QUEUED)
        private var current = ByteArray(0)
        private var position = 0
        @Volatile private var ended = false

        fun offer(bytes: ByteArray) {
            // A connection that stopped reading: its oldest events go
            if (!queue.offer(bytes)) {
                queue.poll()
                queue.offer(bytes)
            }
        }

        fun end() {
            ended = true
            queue.offer(CLOSED)
        }

        override fun read(): Int {
            val one = ByteArray(1)
            return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xFF
        }

        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (position >= current.size) {
                if (ended) return -1
                val next = try {
                    queue.poll(PING_S, TimeUnit.SECONDS)
                } catch (e: InterruptedException) {
                    return -1
                } ?: PING
                if (next === CLOSED) return -1
                current = next
                position = 0
            }
            val count = minOf(len, current.size - position)
            System.arraycopy(current, position, b, off, count)
            position += count
            return count
        }

        override fun close() {
            ended = true
            streams.remove(this)
        }
    }

    private val PING = "{\"type\":\"ping\"}\n".toByteArray(Charsets.UTF_8)
}
