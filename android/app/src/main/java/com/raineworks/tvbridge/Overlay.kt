package com.raineworks.tvbridge

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.TextureView
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

/**
 * Pop-ups over whatever is on screen (an app, the home screen, an HDMI
 * input): a window per screen position, each holding up to [MAX_PER_POSITION]
 * cards, newest last. Everything here runs on the main thread.
 */
class Overlay private constructor(private val context: Context) {

    private class Card(
        val view: View,
        val position: String,
        val player: ExoPlayer?,
        var hide: Runnable? = null,
    )

    private val main = Handler(Looper.getMainLooper())
    private val windows = context.getSystemService(WindowManager::class.java)
    private val containers = HashMap<String, LinearLayout>()
    private val cards = LinkedHashMap<String, Card>()
    private var nextTag = 0

    fun show(request: NotificationRequest) {
        val imageUrl = request.imageUrl
        if (imageUrl != null && request.videoUrl == null) {
            Images.load(imageUrl, 1280) { bitmap -> add(request, bitmap) }
        } else {
            main.post { add(request, null) }
        }
    }

    fun showPairingCode(code: String) {
        main.post {
            if (!Settings.canDrawOverlays(context)) return@post
            val width = dp(420)
            val card = cardLayout(width, null)
            card.addView(text(context.getString(R.string.pairing_title), 22f, true, Color.WHITE))
            card.addView(
                text(code.chunked(3).joinToString(" "), 56f, true, ACCENT).apply {
                    letterSpacing = 0.08f
                    setPadding(0, dp(8), 0, dp(8))
                },
            )
            card.addView(
                text(context.getString(R.string.pairing_text, code), 16f, false, MUTED),
            )
            attach(PAIRING_TAG, "center", card, null, PAIRING_SECONDS)
        }
    }

    fun dismiss(tag: String) {
        main.post { cards[tag]?.let { remove(tag, it, animate = true) } }
    }

    fun dismissAll() {
        main.post { cards.entries.toList().forEach { remove(it.key, it.value, animate = true) } }
    }

    private fun add(request: NotificationRequest, image: Bitmap?) {
        if (!Settings.canDrawOverlays(context)) return
        val width = dp(
            when (request.size) {
                "small" -> 280
                "large" -> 520
                else -> 380
            },
        )
        val scale = when (request.size) {
            "small" -> 0.85f
            "large" -> 1.2f
            else -> 1f
        }
        val card = cardLayout(width, request.color)
        var player: ExoPlayer? = null
        val videoUrl = request.videoUrl
        if (videoUrl != null) {
            val texture = TextureView(context)
            card.addView(texture, LinearLayout.LayoutParams(width, width * 9 / 16))
            player = startVideo(videoUrl, texture, request.mute)
        } else if (image != null) {
            val view = ImageView(context).apply {
                setImageBitmap(image)
                scaleType = ImageView.ScaleType.CENTER_CROP
            }
            val height = (width * image.height / image.width.coerceAtLeast(1))
                .coerceAtMost(width * 3 / 4)
            card.addView(view, LinearLayout.LayoutParams(width, height))
        }
        if (request.title != null || request.message != null) {
            val texts = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(18), dp(14), dp(18), dp(16))
            }
            request.title?.let { texts.addView(text(it, 20f * scale, true, Color.WHITE, maxLines = 2)) }
            request.message?.let {
                texts.addView(
                    text(it, 16f * scale, false, MUTED, maxLines = 6).apply {
                        if (request.title != null) setPadding(0, dp(4), 0, 0)
                    },
                )
            }
            card.addView(texts)
        }
        val tag = request.tag ?: "notification-${nextTag++}"
        attach(tag, request.position, card, player, request.durationS)
    }

    private fun startVideo(url: String, view: TextureView, mute: Boolean): ExoPlayer {
        val item = MediaItem.Builder().setUri(Uri.parse(url)).apply {
            if (url.contains(".m3u8", ignoreCase = true)) setMimeType(MimeTypes.APPLICATION_M3U8)
        }.build()
        return ExoPlayer.Builder(context).build().apply {
            setVideoTextureView(view)
            volume = if (mute) 0f else 1f
            repeatMode = Player.REPEAT_MODE_ONE
            addListener(
                object : Player.Listener {
                    override fun onPlayerError(error: PlaybackException) {
                        Log.w(TAG, "Couldn't play $url: ${error.errorCodeName}")
                    }
                },
            )
            setMediaItem(item)
            prepare()
            playWhenReady = true
        }
    }

    /** Puts a card in its position's window, and takes it away after [seconds]. */
    private fun attach(tag: String, position: String, view: View, player: ExoPlayer?, seconds: Int) {
        cards[tag]?.let { remove(tag, it, animate = false) }
        val container = containers[position] ?: newContainer(position) ?: run {
            player?.release()
            return
        }
        // The oldest go first when a corner is full
        val here = cards.entries.filter { it.value.position == position }
        if (here.size >= MAX_PER_POSITION) {
            here.take(here.size - MAX_PER_POSITION + 1).forEach { remove(it.key, it.value, animate = false) }
        }
        val params = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).apply { setMargins(0, dp(8), 0, dp(8)) }
        container.addView(view, params)
        val card = Card(view, position, player)
        cards[tag] = card
        view.alpha = 0f
        view.translationY = dp(if (position.startsWith("bottom")) 24 else -24).toFloat()
        view.animate().alpha(1f).translationY(0f).setDuration(ANIMATION_MS).start()
        card.hide = Runnable { remove(tag, card, animate = true) }.also {
            main.postDelayed(it, seconds * 1000L)
        }
    }

    private fun remove(tag: String, card: Card, animate: Boolean) {
        if (cards[tag] !== card) return
        cards.remove(tag)
        card.hide?.let { main.removeCallbacks(it) }
        val finish = {
            card.player?.release()
            val container = containers[card.position]
            container?.removeView(card.view)
            if (container != null && container.childCount == 0) {
                try {
                    windows.removeView(container)
                } catch (e: IllegalArgumentException) {
                    Log.w(TAG, "Overlay window already gone: $e")
                }
                containers.remove(card.position)
            }
        }
        if (animate) {
            card.view.animate().alpha(0f).setDuration(ANIMATION_MS).withEndAction { finish() }.start()
        } else {
            finish()
        }
    }

    private fun newContainer(position: String): LinearLayout? {
        val container = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = when (position) {
                "top_left" -> Gravity.TOP or Gravity.START
                "top" -> Gravity.TOP or Gravity.CENTER_HORIZONTAL
                "top_right" -> Gravity.TOP or Gravity.END
                "bottom_left" -> Gravity.BOTTOM or Gravity.START
                "bottom" -> Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
                "bottom_right" -> Gravity.BOTTOM or Gravity.END
                else -> Gravity.CENTER
            }
            // TVs crop their edges (overscan): keep clear of them
            x = if (position == "center" || position == "top" || position == "bottom") 0 else dp(EDGE_DP)
            y = if (position == "center") 0 else dp(EDGE_DP)
            title = "Raineworks TV Bridge"
        }
        container.gravity = if (position.endsWith("right")) Gravity.END else Gravity.START
        return try {
            windows.addView(container, params)
            containers[position] = container
            container
        } catch (e: RuntimeException) {
            // No permission to draw over other apps after all
            Log.w(TAG, "Couldn't add the overlay window: $e")
            null
        }
    }

    private fun cardLayout(width: Int, accent: Int?): LinearLayout =
        LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            minimumWidth = width
            layoutParams = LinearLayout.LayoutParams(width, LinearLayout.LayoutParams.WRAP_CONTENT)
            background = GradientDrawable().apply {
                setColor(CARD)
                cornerRadius = dp(18).toFloat()
                setStroke(dp(2), accent ?: BORDER)
            }
            clipToOutline = true
            elevation = dp(8).toFloat()
        }

    private fun text(value: String, sp: Float, bold: Boolean, color: Int, maxLines: Int = 4): TextView =
        TextView(context).apply {
            text = value
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            if (bold) typeface = Typeface.DEFAULT_BOLD
            this.maxLines = maxLines
            ellipsize = TextUtils.TruncateAt.END
        }

    private fun dp(value: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), context.resources.displayMetrics,
    ).toInt()

    companion object {
        const val PAIRING_TAG = "__pairing__"
        private const val TAG = "TvBridge"
        private const val MAX_PER_POSITION = 3
        private const val PAIRING_SECONDS = 300
        private const val EDGE_DP = 40
        private const val ANIMATION_MS = 250L
        private val CARD = Color.argb(240, 21, 27, 43)
        private val BORDER = Color.argb(255, 48, 58, 82)
        private val ACCENT = Color.rgb(66, 165, 245)
        private val MUTED = Color.rgb(200, 208, 222)

        @Volatile
        private var instance: Overlay? = null

        fun get(context: Context): Overlay =
            instance ?: synchronized(this) {
                instance ?: Overlay(context.applicationContext).also { instance = it }
            }
    }
}
