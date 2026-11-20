package com.raineworks.tvbridge

import android.content.Context
import android.graphics.Bitmap
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
            val width = dp(380)
            val card = cardLayout(width, null, pill = false).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                setPadding(dp(28), dp(24), dp(28), dp(24))
            }
            card.addView(
                ImageView(context).apply { setImageResource(R.drawable.logo_white) },
                LinearLayout.LayoutParams(dp(44), dp(44)).apply { bottomMargin = dp(14) },
            )
            card.addView(text(context.getString(R.string.pairing_title), 18f, Theme.semibold(context), Theme.FOREGROUND, 2))
            card.addView(
                text(code.chunked(3).joinToString(" "), 44f, Theme.semibold(context), Theme.FOREGROUND, 1).apply {
                    letterSpacing = 0.12f
                    setPadding(0, dp(10), 0, dp(6))
                },
            )
            card.addView(
                text(context.getString(R.string.pairing_hint), 13f, Theme.regular(context), Theme.MUTED_FOREGROUND, 3).apply {
                    gravity = Gravity.CENTER
                },
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
        val card = if (request.size == "compact") compactCard(request, image) else fullCard(request, image)
        val tag = request.tag ?: "notification-${nextTag++}"
        attach(tag, request.position, card.first, card.second, request.durationS)
    }

    /** A one-line pill: the logo (or the image, small), the title and message. */
    private fun compactCard(request: NotificationRequest, image: Bitmap?): Pair<View, ExoPlayer?> {
        val pill = cardLayout(LinearLayout.LayoutParams.WRAP_CONTENT, request.color, pill = true).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(16), dp(8))
        }
        pill.addView(badge(request.color, image, 24), LinearLayout.LayoutParams(dp(24), dp(24)))
        val line = listOfNotNull(request.title, request.message).joinToString("  ·  ")
        pill.addView(
            text(line.ifEmpty { context.getString(R.string.app_name) }, 13f, Theme.medium(context), Theme.FOREGROUND, 1).apply {
                maxWidth = dp(420)
                setPadding(dp(10), 0, 0, 0)
            },
        )
        return pill to null
    }

    /** A card: the image or video on top, then the logo, title and message, then time left. */
    private fun fullCard(request: NotificationRequest, image: Bitmap?): Pair<View, ExoPlayer?> {
        val width = dp(
            when (request.size) {
                "medium" -> 340
                "large" -> 440
                else -> 280
            },
        )
        val scale = when (request.size) {
            "medium" -> 1.08f
            "large" -> 1.22f
            else -> 1f
        }
        val card = cardLayout(width, request.color, pill = false)
        var player: ExoPlayer? = null
        val videoUrl = request.videoUrl
        if (videoUrl != null) {
            val texture = TextureView(context)
            card.addView(texture, LinearLayout.LayoutParams(width, width * 9 / 16))
            player = startVideo(videoUrl, texture, request.mute)
        } else if (image != null) {
            val height = (width * image.height / image.width.coerceAtLeast(1)).coerceAtMost(width * 3 / 4)
            card.addView(
                ImageView(context).apply {
                    setImageBitmap(image)
                    scaleType = ImageView.ScaleType.CENTER_CROP
                },
                LinearLayout.LayoutParams(width, height),
            )
        }
        if (request.title != null || request.message != null) {
            val row = LinearLayout(context).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.TOP
                setPadding(dp(14 * scale), dp(12 * scale), dp(16 * scale), dp(13 * scale))
            }
            val badgeSize = (22 * scale).toInt()
            row.addView(
                badge(request.color, null, badgeSize),
                LinearLayout.LayoutParams(dp(badgeSize), dp(badgeSize)).apply { topMargin = dp(1) },
            )
            val texts = LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(11 * scale), 0, 0, 0)
            }
            request.title?.let {
                texts.addView(text(it, 14f * scale, Theme.semibold(context), Theme.FOREGROUND, 2))
            }
            request.message?.let {
                texts.addView(
                    text(it, 13f * scale, Theme.regular(context), Theme.MUTED_FOREGROUND, 3).apply {
                        if (request.title != null) setPadding(0, dp(2), 0, 0)
                        setLineSpacing(0f, 1.1f)
                    },
                )
            }
            row.addView(texts, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            card.addView(row, LinearLayout.LayoutParams(width, LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        // Time left: a hairline that runs out with the pop-up
        card.addView(
            View(context).apply {
                setBackgroundColor(Theme.withAlpha(request.color ?: Theme.FOREGROUND, 90))
                pivotX = 0f
                animate().scaleX(0f).setDuration(request.durationS * 1000L)
                    .setInterpolator(android.view.animation.LinearInterpolator()).start()
            },
            LinearLayout.LayoutParams(width, dp(2)),
        )
        return card to player
    }

    /** The logo in a soft circle (tinted with the notification's color), or a small image. */
    private fun badge(color: Int?, image: Bitmap?, sizeDp: Int): View {
        if (image != null) {
            return ImageView(context).apply {
                setImageBitmap(image)
                scaleType = ImageView.ScaleType.CENTER_CROP
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Theme.MUTED)
                }
                clipToOutline = true
            }
        }
        val tint = color ?: Theme.FOREGROUND
        return ImageView(context).apply {
            setImageResource(R.drawable.logo_white)
            imageTintList = android.content.res.ColorStateList.valueOf(tint)
            val pad = dp(sizeDp) / 8
            setPadding(pad, pad, pad, pad)
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Theme.withAlpha(tint, 28))
            }
        }
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
        ).apply { setMargins(0, dp(5), 0, dp(5)) }
        container.addView(view, params)
        val card = Card(view, position, player)
        cards[tag] = card
        view.alpha = 0f
        view.translationY = dp(if (position.startsWith("bottom")) 12 else -12).toFloat()
        view.animate().alpha(1f).translationY(0f).setDuration(ANIMATION_MS)
            .setInterpolator(android.view.animation.DecelerateInterpolator(1.5f)).start()
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

    private fun cardLayout(width: Int, accent: Int?, pill: Boolean): LinearLayout =
        LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(width, LinearLayout.LayoutParams.WRAP_CONTENT)
            background = GradientDrawable().apply {
                setColor(Theme.withAlpha(Theme.CARD, 246))
                cornerRadius = if (pill) dp(999).toFloat() else dp(Theme.RADIUS_DP).toFloat()
                setStroke(dp(1), accent?.let { Theme.withAlpha(it, 110) } ?: Theme.BORDER)
            }
            clipToOutline = true
            elevation = dp(6).toFloat()
        }

    private fun text(value: String, sp: Float, typeface: Typeface, color: Int, maxLines: Int): TextView =
        TextView(context).apply {
            text = value
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            this.typeface = typeface
            this.maxLines = maxLines
            ellipsize = TextUtils.TruncateAt.END
            includeFontPadding = false
        }

    private fun dp(value: Number): Int = Theme.dp(context, value)

    companion object {
        const val PAIRING_TAG = "__pairing__"
        private const val TAG = "TvBridge"
        private const val MAX_PER_POSITION = 3
        private const val PAIRING_SECONDS = 300
        private const val EDGE_DP = 28
        private const val ANIMATION_MS = 220L

        @Volatile
        private var instance: Overlay? = null

        fun get(context: Context): Overlay =
            instance ?: synchronized(this) {
                instance ?: Overlay(context.applicationContext).also { instance = it }
            }
    }
}
