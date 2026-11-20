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
 * input): a window per screen position, a stack of cards in each. Persistent
 * cards are pinned at the head of the stack; [MAX_VISIBLE] show, the newest
 * first after the pinned ones, and a "+N more" pill counts the rest, which
 * come back as others go. A card sent again with its tag is updated in its
 * place (a camera keeps playing). Everything here runs on the main thread.
 */
class Overlay private constructor(private val context: Context) {

    private class Card(
        val position: String,
        var view: View,
        var player: ExoPlayer?,
        var videoUrl: String?,
        var pinned: Boolean,
        var hide: Runnable? = null,
    )

    /** A card's view, and the surface its video plays on. */
    private class Built(val view: View, val texture: TextureView?)

    private val main = Handler(Looper.getMainLooper())
    private val windows = context.getSystemService(WindowManager::class.java)
    private val containers = HashMap<String, LinearLayout>()
    private val mores = HashMap<String, TextView>()
    private val cards = LinkedHashMap<String, Card>()
    private var nextTag = 0

    /** The tags of the pop-ups up now (read from the API's thread). */
    @Volatile
    var tags: List<String> = emptyList()
        private set

    fun show(request: NotificationRequest, ticket: Long) {
        // An image icon first, then the image, then the card
        val icon = request.icon?.takeUnless { Icons.isMdi(it) }
        val withImage = { iconBitmap: Bitmap? ->
            val imageUrl = request.imageUrl
            if (imageUrl != null && request.videoUrl == null) {
                Images.load(imageUrl, 1280) { bitmap -> add(request, ticket, bitmap, iconBitmap) }
            } else {
                main.post { add(request, ticket, null, iconBitmap) }
            }
        }
        if (icon != null) Images.load(icon, 128) { bitmap -> withImage(bitmap) } else withImage(null)
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
            attach(PAIRING_TAG, "center", card, null, null, PAIRING_SECONDS, pinned = false)
        }
    }

    fun dismiss(tag: String) {
        main.post { cards[tag]?.let { remove(tag, it, animate = true) } }
    }

    /** Takes every pop-up down, but a pairing code. */
    fun dismissAll() {
        main.post {
            cards.entries.filter { it.key != PAIRING_TAG }.forEach { remove(it.key, it.value, animate = true) }
        }
    }

    private fun add(request: NotificationRequest, ticket: Long, image: Bitmap?, iconBitmap: Bitmap?) {
        // Dismissed, or updated again, while its images loaded
        if (!Notifier.isCurrent(request.tag, ticket)) return
        if (!Settings.canDrawOverlays(context)) return
        val built = if (request.size == "compact") {
            compactCard(request, image, iconBitmap)
        } else {
            fullCard(request, image, iconBitmap)
        }
        val tag = request.tag ?: "$AUTO_TAG${nextTag++}"
        val existing = cards[tag]
        if (existing != null && existing.position == request.position) {
            update(tag, existing, built, request)
        } else {
            existing?.let { remove(tag, it, animate = false) }
            val player = built.texture?.let { startVideo(request.videoUrl!!, it, request.mute) }
            attach(tag, request.position, built.view, player, request.videoUrl, request.durationS, request.persistent)
        }
    }

    /** The card with [tag] shown anew in its place: no animation, its video still playing. */
    private fun update(tag: String, card: Card, built: Built, request: NotificationRequest) {
        val container = containers[card.position] ?: return
        val index = container.indexOfChild(card.view)
        if (index < 0) return
        built.view.visibility = card.view.visibility
        container.removeViewAt(index)
        container.addView(built.view, index, cardParams())
        val player = card.player
        val texture = built.texture
        if (player != null && texture != null && card.videoUrl == request.videoUrl) {
            player.setVideoTextureView(texture)
            player.volume = if (request.mute) 0f else 1f
        } else {
            player?.release()
            card.player = texture?.let { startVideo(request.videoUrl!!, it, request.mute) }
        }
        card.view = built.view
        card.videoUrl = request.videoUrl
        card.pinned = request.persistent
        schedule(tag, card, request.durationS)
        layout(card.position)
    }

    /**
     * A one-line pill: the logo (or the icon, or the image, small; or the
     * live video as a small tile), the title and message.
     */
    private fun compactCard(request: NotificationRequest, image: Bitmap?, iconBitmap: Bitmap?): Built {
        val pill = cardLayout(LinearLayout.LayoutParams.WRAP_CONTENT, request.color, pill = true).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(16), dp(8))
        }
        var texture: TextureView? = null
        if (request.videoUrl != null) {
            // Live video: a small rounded 16:9 tile where the logo goes
            // Concentric corners: the card's radius is the tile's plus the gap
            val gap = 6
            val tileRadius = 10
            val tile = android.widget.FrameLayout(context).apply {
                background = GradientDrawable().apply {
                    setColor(Theme.MUTED)
                    cornerRadius = dp(tileRadius).toFloat()
                }
                clipToOutline = true
            }
            texture = TextureView(context)
            tile.addView(texture, android.widget.FrameLayout.LayoutParams(dp(72), dp(40)))
            pill.addView(tile, LinearLayout.LayoutParams(dp(72), dp(40)))
            pill.setPadding(dp(gap), dp(gap), dp(16), dp(gap))
            (pill.background as GradientDrawable).cornerRadius = dp(tileRadius + gap).toFloat()
        } else {
            pill.addView(
                badge(request.color, iconBitmap ?: image, request.icon, 24),
                LinearLayout.LayoutParams(dp(24), dp(24)),
            )
        }
        val line = listOfNotNull(request.title, request.message).joinToString("  ·  ")
        pill.addView(
            text(line.ifEmpty { context.getString(R.string.app_name) }, 13f, Theme.medium(context), Theme.FOREGROUND, 1).apply {
                maxWidth = dp(420)
                setPadding(dp(10), 0, 0, 0)
            },
        )
        request.progress?.let {
            pill.addView(
                progressBar(it, request.color).apply {
                    background = GradientDrawable().apply {
                        setColor(Theme.MUTED)
                        cornerRadius = dp(2).toFloat()
                    }
                    clipToOutline = true
                },
                LinearLayout.LayoutParams(dp(56), dp(4)).apply { marginStart = dp(12) },
            )
        }
        return Built(pill, texture)
    }

    /**
     * A card: the image or video on top, then the logo, title and message,
     * then its progress, or the time it has left.
     */
    private fun fullCard(request: NotificationRequest, image: Bitmap?, iconBitmap: Bitmap?): Built {
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
        var texture: TextureView? = null
        if (request.videoUrl != null) {
            texture = TextureView(context)
            card.addView(texture, LinearLayout.LayoutParams(width, width * 9 / 16))
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
                badge(request.color, iconBitmap, request.icon, badgeSize),
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
        val progress = request.progress
        if (progress != null) {
            card.addView(progressBar(progress, request.color), LinearLayout.LayoutParams(width, dp(3)))
        } else if (!request.persistent) {
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
        }
        return Built(card, texture)
    }

    /** A bar filled to [progress] (0 to 100) in the notification's color. */
    private fun progressBar(progress: Int, color: Int?): LinearLayout =
        LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Theme.MUTED)
            addView(
                View(context).apply { setBackgroundColor(color ?: Theme.FOREGROUND) },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, progress.toFloat()),
            )
            addView(View(context), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, (100 - progress).toFloat()))
        }

    /**
     * The badge in a soft circle (tinted by the notification's color): an
     * image, a Home Assistant icon ("mdi:doorbell"), else the logo.
     */
    private fun badge(color: Int?, image: Bitmap?, icon: String?, sizeDp: Int): View {
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
        val circle = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Theme.withAlpha(tint, 28))
        }
        val glyph = icon?.takeIf { Icons.isMdi(it) }?.let { Icons.glyph(context, it) }
        if (glyph != null) {
            return TextView(context).apply {
                text = glyph
                typeface = Icons.typeface(context)
                setTextColor(tint)
                setTextSize(TypedValue.COMPLEX_UNIT_DIP, sizeDp * 0.62f)
                gravity = Gravity.CENTER
                includeFontPadding = false
                background = circle
            }
        }
        return ImageView(context).apply {
            setImageResource(R.drawable.logo_white)
            imageTintList = android.content.res.ColorStateList.valueOf(tint)
            val pad = dp(sizeDp) / 8
            setPadding(pad, pad, pad, pad)
            background = circle
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

    /**
     * Puts a card in its position's window (a pinned one after the pinned
     * ones, else last), and takes it away after [seconds] (0: it stays).
     */
    private fun attach(
        tag: String,
        position: String,
        view: View,
        player: ExoPlayer?,
        videoUrl: String?,
        seconds: Int,
        pinned: Boolean,
    ) {
        cards[tag]?.let { remove(tag, it, animate = false) }
        val container = containers[position] ?: newContainer(position) ?: run {
            player?.release()
            return
        }
        // Keep a corner's stack bounded: the oldest timed ones go first
        val here = cards.entries.filter { it.value.position == position }
        if (here.size >= MAX_KEPT) {
            (here.filterNot { it.value.pinned } + here.filter { it.value.pinned })
                .take(here.size - MAX_KEPT + 1)
                .forEach { remove(it.key, it.value, animate = false) }
        }
        val lastPinned = cards.values.filter { it.position == position && it.pinned }
            .maxOfOrNull { container.indexOfChild(it.view) } ?: -1
        val more = mores[position]?.let { container.indexOfChild(it) }?.takeIf { it >= 0 }
        container.addView(view, if (pinned) lastPinned + 1 else more ?: container.childCount, cardParams())
        val card = Card(position, view, player, videoUrl, pinned)
        cards[tag] = card
        view.alpha = 0f
        view.translationY = dp(if (position.startsWith("bottom")) 12 else -12).toFloat()
        view.animate().alpha(1f).translationY(0f).setDuration(ANIMATION_MS)
            .setInterpolator(android.view.animation.DecelerateInterpolator(1.5f)).start()
        schedule(tag, card, seconds)
        layout(position)
    }

    /** Takes [card] down after [seconds] from now (0: never), in place of any earlier timer. */
    private fun schedule(tag: String, card: Card, seconds: Int) {
        card.hide?.let { main.removeCallbacks(it) }
        card.hide = if (seconds > 0) {
            Runnable { remove(tag, card, animate = true) }.also { main.postDelayed(it, seconds * 1000L) }
        } else {
            null
        }
    }

    private fun remove(tag: String, card: Card, animate: Boolean) {
        if (cards[tag] !== card) return
        cards.remove(tag)
        card.hide?.let { main.removeCallbacks(it) }
        val finish = {
            card.player?.release()
            containers[card.position]?.removeView(card.view)
            layout(card.position)
        }
        if (animate && card.view.visibility == View.VISIBLE) {
            card.view.animate().alpha(0f).setDuration(ANIMATION_MS).withEndAction { finish() }.start()
        } else {
            finish()
        }
        // At once, not after the animation: Home Assistant may ask meanwhile
        tags = cards.keys.filterNot { it.startsWith(AUTO_TAG) || it == PAIRING_TAG }
    }

    /**
     * Which of a position's cards show: the pinned ones, then the newest,
     * [MAX_VISIBLE] in all, and a "+N more" pill under them for the rest.
     * The window goes when its last card has.
     */
    private fun layout(position: String) {
        tags = cards.keys.filterNot { it.startsWith(AUTO_TAG) || it == PAIRING_TAG }
        val container = containers[position] ?: return
        val here = cards.values.filter { it.position == position }
        val visible = (here.filter { it.pinned } + here.filterNot { it.pinned }.asReversed())
            .take(MAX_VISIBLE).toSet()
        here.forEach { it.view.visibility = if (it in visible) View.VISIBLE else View.GONE }
        val hidden = here.size - visible.size
        val more = mores[position]
        if (hidden > 0) {
            val pill = more ?: morePill().also { mores[position] = it }
            pill.text = context.getString(R.string.more_popups, hidden)
            if (container.indexOfChild(pill) != container.childCount - 1) {
                container.removeView(pill)
                container.addView(pill, cardParams())
            }
        } else if (more != null) {
            container.removeView(more)
            mores.remove(position)
        }
        // Cards still fading out keep the window until they've gone
        if (container.childCount == 0) {
            try {
                windows.removeView(container)
            } catch (e: IllegalArgumentException) {
                Log.w(TAG, "Overlay window already gone: $e")
            }
            containers.remove(position)
        }
    }

    private fun morePill(): TextView =
        text("", 12f, Theme.medium(context), Theme.MUTED_FOREGROUND, 1).apply {
            setPadding(dp(14), dp(7), dp(14), dp(7))
            background = GradientDrawable().apply {
                setColor(Theme.withAlpha(Theme.CARD, 246))
                cornerRadius = dp(999).toFloat()
                setStroke(dp(1), Theme.BORDER)
            }
        }

    private fun cardParams(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { setMargins(0, dp(5), 0, dp(5)) }

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
        private const val MAX_VISIBLE = 3
        private const val MAX_KEPT = 12
        private const val AUTO_TAG = "__auto__"
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
