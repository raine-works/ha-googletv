package com.raineworks.tvbridge

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** Images for notifications, downloaded off the main thread, scaled down. */
object Images {
    private val pool = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())
    private const val MAX_BYTES = 15 * 1024 * 1024

    /** Loads [url], no bigger than [maxSide] px, then calls [done] on the main thread (null on failure). */
    fun load(url: String, maxSide: Int, done: (Bitmap?) -> Unit) {
        pool.execute {
            val bitmap = try {
                decode(download(url), maxSide)
            } catch (e: Exception) {
                android.util.Log.w("TvBridge", "Couldn't load image $url: $e")
                null
            }
            main.post { done(bitmap) }
        }
    }

    private fun download(url: String): ByteArray {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 8000
        connection.readTimeout = 10000
        connection.instanceFollowRedirects = true
        try {
            require(connection.responseCode in 200..299) { "HTTP ${connection.responseCode}" }
            connection.inputStream.use { stream ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(16 * 1024)
                while (true) {
                    val read = stream.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    require(out.size() <= MAX_BYTES) { "Image over ${MAX_BYTES / 1024 / 1024} MB" }
                }
                return out.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun decode(bytes: ByteArray, maxSide: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxSide || bounds.outHeight / (sample * 2) >= maxSide) {
            sample *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
    }
}
