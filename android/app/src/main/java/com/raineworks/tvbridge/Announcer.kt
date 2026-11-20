package com.raineworks.tvbridge

import android.content.Context
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

/**
 * Announcements (text-to-speech, a chime): spoken over whatever's on, which
 * ducks and comes back, instead of taking over the screen. One after
 * another, with a pill showing what's said while it's said.
 */
object Announcer {
    private const val TAG = "TvBridge"
    const val PILL_TAG = "announcement"
    // Longest an announcement may hold the TV's sound (a stalled stream)
    private const val MAX_MS = 60_000L
    private const val MAX_QUEUED = 8

    private val main = Handler(Looper.getMainLooper())
    private var player: ExoPlayer? = null
    private var focus: AudioFocusRequest? = null
    private val queue = ArrayDeque<PlayRequest>()
    private var watchdog: Runnable? = null

    fun announce(context: Context, request: PlayRequest) {
        val app = context.applicationContext
        main.post {
            if (queue.size >= MAX_QUEUED) queue.removeFirst()
            queue.addLast(request)
            if (player == null) next(app)
        }
    }

    fun stop(context: Context) {
        main.post {
            queue.clear()
            finish(context.applicationContext)
        }
    }

    private fun next(context: Context) {
        val request = queue.removeFirstOrNull() ?: return finish(context)
        val audio = context.getSystemService(AudioManager::class.java)
        if (focus == null) {
            focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(
                    android.media.AudioAttributes.Builder()
                        .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                )
                .build()
                .also {
                    if (audio.requestAudioFocus(it) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                        Log.w(TAG, "Audio focus refused: announcing anyway")
                    }
                }
        }
        showPill(context, request)
        watchdog = Runnable {
            Log.w(TAG, "Announcement ${request.url} took too long: stopped")
            done(context)
        }.also { main.postDelayed(it, MAX_MS) }
        player = ExoPlayer.Builder(context).build().apply {
            setAudioAttributes(
                AudioAttributes.Builder().setUsage(C.USAGE_ASSISTANT).setContentType(C.AUDIO_CONTENT_TYPE_SPEECH).build(),
                false,
            )
            addListener(
                object : Player.Listener {
                    override fun onPlaybackStateChanged(state: Int) {
                        if (state == Player.STATE_ENDED) done(context)
                    }

                    override fun onPlayerError(error: PlaybackException) {
                        Log.w(TAG, "Couldn't announce ${request.url}: ${error.errorCodeName}")
                        done(context)
                    }
                },
            )
            setMediaItem(MediaItem.fromUri(request.url))
            prepare()
            playWhenReady = true
        }
    }

    private fun done(context: Context) {
        watchdog?.let { main.removeCallbacks(it) }
        watchdog = null
        player?.release()
        player = null
        if (queue.isEmpty()) finish(context) else next(context)
    }

    private fun finish(context: Context) {
        watchdog?.let { main.removeCallbacks(it) }
        watchdog = null
        player?.release()
        player = null
        focus?.let { context.getSystemService(AudioManager::class.java).abandonAudioFocusRequest(it) }
        focus = null
        Notifier.dismiss(context, PILL_TAG)
    }

    /** What's being said, on a compact pill (kept out of the panel). */
    private fun showPill(context: Context, request: PlayRequest) {
        val text = request.message ?: request.title
        // Nothing to say, or nowhere to say it (not to the panel): no pill
        if (text == null || !TvInfo.overlayAllowed(context)) {
            Notifier.dismiss(context, PILL_TAG)
            return
        }
        val prefs = Prefs(context)
        Notifier.handle(
            context,
            NotificationRequest(
                title = text, message = null, imageUrl = null, videoUrl = null,
                mode = NotificationRequest.MODE_POPUP, position = prefs.defaultPosition,
                durationS = 0, size = "compact", color = null, mute = true,
                ignoreRules = false, whenBlocked = Prefs.WHEN_BLOCKED_DROP, tag = PILL_TAG,
                icon = "mdi:bullhorn", contextApp = null, contextInput = null,
            ),
        )
    }
}
