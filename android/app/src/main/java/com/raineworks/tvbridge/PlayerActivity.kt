package com.raineworks.tvbridge

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.ui.PlayerView

/**
 * Home Assistant's media, full screen: a video, a song (its cover, title and
 * artist), or an image. Its media session is the TV's like any app's, so
 * Home Assistant sees what's playing and the remote's media keys work. Back,
 * the end of the media, or Home Assistant's stop closes it.
 */
// PlayerView's controller and artwork settings are media3's "unstable" API
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
class PlayerActivity : Activity() {

    private var player: ExoPlayer? = null
    private var session: MediaSession? = null
    private lateinit var root: FrameLayout
    // A song's progress: its bar, moved along while it plays
    private var progress: View? = null
    private val tick = object : Runnable {
        override fun run() {
            val exo = player ?: return
            val bar = progress ?: return
            val duration = exo.duration
            if (duration > 0) bar.scaleX = (exo.currentPosition.toFloat() / duration).coerceIn(0f, 1f)
            bar.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        setContentView(root)
        current = this
        show(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        show(intent)
    }

    override fun onStop() {
        super.onStop()
        // Left for another app or the home screen: done
        finish()
    }

    override fun onDestroy() {
        if (current === this) current = null
        release()
        super.onDestroy()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        // A song: select plays and pauses, left and right skip
        if (progress != null) {
            val exo = player ?: return super.onKeyDown(keyCode, event)
            when (keyCode) {
                KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> exo.playWhenReady = !exo.playWhenReady
                KeyEvent.KEYCODE_DPAD_LEFT -> exo.seekTo((exo.currentPosition - SKIP_MS).coerceAtLeast(0))
                KeyEvent.KEYCODE_DPAD_RIGHT -> exo.seekTo(exo.currentPosition + SKIP_MS)
                else -> return super.onKeyDown(keyCode, event)
            }
            return true
        }
        // A video: the D-pad shows the controls (play, pause, seek)
        (root.getChildAt(0) as? PlayerView)?.let { view ->
            if (!view.isControllerFullyVisible && keyCode in DPAD) {
                view.showController()
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun release() {
        session?.release()
        session = null
        player?.release()
        player = null
    }

    private fun show(intent: Intent) {
        val request = requests.remove(intent.getStringExtra(EXTRA_ID)) ?: run {
            finish()
            return
        }
        release()
        progress = null
        root.removeAllViews()
        if (request.kind == "image") {
            val image = ImageView(this).apply { scaleType = ImageView.ScaleType.FIT_CENTER }
            root.addView(image, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            Images.load(request.url, 1920) { bitmap ->
                if (bitmap != null) image.setImageBitmap(bitmap) else finish()
            }
            return
        }
        val exo = ExoPlayer.Builder(this)
            // Media's audio focus: another app's media pauses it, an announcement ducks it
            .setAudioAttributes(
                androidx.media3.common.AudioAttributes.Builder()
                    .setUsage(androidx.media3.common.C.USAGE_MEDIA)
                    .setContentType(
                        if (request.kind == "audio") androidx.media3.common.C.AUDIO_CONTENT_TYPE_MUSIC
                        else androidx.media3.common.C.AUDIO_CONTENT_TYPE_MOVIE,
                    )
                    .build(),
                true,
            )
            .build()
        player = exo
        session = MediaSession.Builder(this, exo).setId("home-assistant-${System.nanoTime()}").build()
        val view = PlayerView(this).apply {
            this.player = exo
            setShowBuffering(PlayerView.SHOW_BUFFERING_ALWAYS)
            // A song has its own card and keys; a video the player's controls
            useController = request.kind != "audio"
            controllerShowTimeoutMs = 3000
            // A song's own card shows its cover: not the player's
            defaultArtwork = null
            artworkDisplayMode = PlayerView.ARTWORK_DISPLAY_MODE_OFF
        }
        root.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        if (request.kind == "audio") {
            root.addView(nowPlaying(request), FrameLayout.LayoutParams(dp(880), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
            progress?.post(tick)
        }
        exo.addListener(
            object : Player.Listener {
                override fun onPlaybackStateChanged(state: Int) {
                    if (state == Player.STATE_ENDED) finish()
                }

                override fun onPlayerError(error: PlaybackException) {
                    Log.w(TAG, "Couldn't play ${request.url}: ${error.errorCodeName}")
                    finish()
                }
            },
        )
        val metadata = MediaMetadata.Builder()
            .setTitle(request.title)
            .setArtist(request.artist)
            .setArtworkUri(request.imageUrl?.let { Uri.parse(it) })
            .build()
        exo.setMediaItem(
            MediaItem.Builder().setUri(request.url).setMediaMetadata(metadata).apply {
                when {
                    request.mime != null -> setMimeType(request.mime)
                    request.url.contains(".m3u8", ignoreCase = true) -> setMimeType(MimeTypes.APPLICATION_M3U8)
                }
            }.build(),
        )
        exo.prepare()
        exo.playWhenReady = true
    }

    /** A song: its cover, title and artist, in the app's look. */
    private fun nowPlaying(request: PlayRequest): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val cover = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            background = Theme.surface(this@PlayerActivity, Theme.MUTED, 16)
            clipToOutline = true
            setImageResource(R.drawable.logo_gtv)
            val pad = dp(56)
            setPadding(pad, pad, pad, pad)
        }
        row.addView(cover, LinearLayout.LayoutParams(dp(280), dp(280)))
        request.imageUrl?.let { url ->
            Images.load(url, 720) { bitmap ->
                if (bitmap != null) {
                    cover.setPadding(0, 0, 0, 0)
                    cover.setImageBitmap(bitmap)
                }
            }
        }
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(40), 0, 0, 0)
        }
        texts.addView(label(request.title ?: getString(R.string.player_untitled), 34f, Theme.FOREGROUND, Theme.semibold(this)))
        request.artist?.let { texts.addView(label(it, 20f, Theme.MUTED_FOREGROUND, Theme.regular(this)).apply { setPadding(0, dp(8), 0, 0) }) }
        val track = FrameLayout(this).apply {
            background = Theme.surface(this@PlayerActivity, Theme.MUTED, 2, Theme.MUTED)
            clipToOutline = true
        }
        val bar = View(this).apply {
            setBackgroundColor(Theme.FOREGROUND)
            pivotX = 0f
            scaleX = 0f
        }
        track.addView(bar, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        progress = bar
        texts.addView(
            track,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(4)).apply { topMargin = dp(28) },
        )
        texts.addView(label(getString(R.string.player_from), 14f, Theme.MUTED_FOREGROUND, Theme.medium(this)).apply { setPadding(0, dp(16), 0, 0) })
        row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        return row
    }

    private fun label(value: String, sp: Float, color: Int, typeface: android.graphics.Typeface): TextView =
        TextView(this).apply {
            text = value
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            this.typeface = typeface
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
            includeFontPadding = false
        }

    private fun dp(value: Number): Int = Theme.dp(this, value)

    companion object {
        private const val TAG = "TvBridge"
        private const val EXTRA_ID = "request"
        private const val SKIP_MS = 10_000L
        private val DPAD = setOf(
            KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN, KeyEvent.KEYCODE_DPAD_LEFT,
            KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER,
        )

        // Requests by id, handed from the API's thread to the activity
        private val requests = java.util.concurrent.ConcurrentHashMap<String, PlayRequest>()

        @Volatile
        private var current: PlayerActivity? = null

        /** Plays [request] full screen, over whatever's on (the overlay permission allows it). */
        fun start(context: Context, request: PlayRequest) {
            val id = java.util.UUID.randomUUID().toString()
            requests[id] = request
            context.startActivity(
                Intent(context, PlayerActivity::class.java)
                    .putExtra(EXTRA_ID, id)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
        }

        /** Closes the player, if it's up. */
        fun stop() {
            current?.let { activity -> activity.runOnUiThread { activity.finish() } }
        }
    }
}
