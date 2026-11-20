package com.raineworks.tvbridge

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Video clips for pop-ups, downloaded whole before they play, then played
 * from the file (so a signed URL's expiry doesn't matter, and a loop
 * doesn't fetch it again).
 *
 * Some servers end a clip early: UniFi Protect declares each clip a few KB
 * longer than it is, and Home Assistant cuts the response at the real end.
 * A download that ends short is kept when it's a complete MP4 (its
 * top-level boxes add up to the file exactly); otherwise it's tried again.
 */
object Clips {
    private const val TAG = "TvBridge"
    private const val ATTEMPTS = 3
    private const val MAX_BYTES = 300L * 1024 * 1024
    // Clips left behind (the app stopped with one up) go after this long
    private const val STALE_MS = 60 * 60 * 1000L

    private val pool = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())

    /** A live stream (HLS, RTSP), played as it comes rather than downloaded. */
    fun isStream(url: String): Boolean =
        url.contains(".m3u8", ignoreCase = true) || url.startsWith("rtsp://", ignoreCase = true)

    /** Downloads [url], then calls [done] on the main thread with the file (null on failure). */
    fun fetch(context: Context, url: String, done: (File?) -> Unit) {
        val dir = File(context.cacheDir, "clips").apply { mkdirs() }
        pool.execute {
            dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > STALE_MS }?.forEach { it.delete() }
            val file = File(dir, "${UUID.randomUUID()}.clip")
            var got: File? = null
            for (attempt in 1..ATTEMPTS) {
                try {
                    if (download(url, file)) {
                        got = file
                        break
                    }
                    Log.w(TAG, "Clip $attempt of $ATTEMPTS ended early: ${redact(url)}")
                } catch (e: Exception) {
                    Log.w(TAG, "Couldn't download clip ${redact(url)} ($attempt of $ATTEMPTS): $e")
                }
                if (attempt < ATTEMPTS) Thread.sleep(1000L * attempt)
            }
            if (got == null) file.delete()
            main.post { done(got) }
        }
    }

    /**
     * Downloads [url] into [file]: whether it's whole (all the bytes the
     * server declared, or short but a complete MP4).
     */
    private fun download(url: String, file: File): Boolean {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 8000
        connection.readTimeout = 20000
        connection.instanceFollowRedirects = true
        try {
            if (connection.responseCode !in 200..299) throw IOException("HTTP ${connection.responseCode}")
            val declared = connection.contentLengthLong
            var read = 0L
            var cut = false
            file.outputStream().use { out ->
                connection.inputStream.use { stream ->
                    val buffer = ByteArray(64 * 1024)
                    try {
                        while (true) {
                            val n = stream.read(buffer)
                            if (n < 0) break
                            out.write(buffer, 0, n)
                            read += n
                            if (read > MAX_BYTES) throw IOException("Clip over ${MAX_BYTES / 1024 / 1024} MB")
                        }
                    } catch (e: IOException) {
                        if (read > MAX_BYTES) throw e
                        // "unexpected end of stream": the server stopped short of what it
                        // declared (or the network dropped): the check below tells which
                        cut = true
                    }
                }
            }
            val short = cut || (declared >= 0 && read < declared)
            return !short || isCompleteMp4(file)
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Whether [file] is a whole MP4: an ftyp first, a moov somewhere, and the
     * top-level boxes' sizes adding up to its length exactly.
     */
    fun isCompleteMp4(file: File): Boolean = try {
        RandomAccessFile(file, "r").use { mp4 ->
            val length = mp4.length()
            var offset = 0L
            var first = true
            var moov = false
            while (offset < length) {
                if (length - offset < 8) return false
                mp4.seek(offset)
                var size = mp4.readInt().toLong() and 0xFFFFFFFFL
                val type = ByteArray(4).also { mp4.readFully(it) }.toString(Charsets.US_ASCII)
                if (size == 1L) {
                    if (length - offset < 16) return false
                    size = mp4.readLong()
                } else if (size == 0L) {
                    // To the end of the file
                    size = length - offset
                }
                if (size < 8) return false
                if (first && type != "ftyp") return false
                if (type == "moov") moov = true
                first = false
                offset += size
            }
            offset == length && moov
        }
    } catch (e: IOException) {
        false
    }

    /** A URL for the log, its signature left out. */
    private fun redact(url: String): String = url.substringBefore('?')
}
