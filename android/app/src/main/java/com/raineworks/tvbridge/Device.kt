package com.raineworks.tvbridge

import android.app.ActivityManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.media.tv.TvContract
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Environment
import android.os.StatFs
import android.os.SystemClock
import android.provider.Settings
import android.view.KeyEvent
import org.json.JSONArray
import org.json.JSONObject

/**
 * The TV for Home Assistant without ADB: what it's doing, and what an app may
 * do to it (media and volume keys, opening apps, links and inputs). What
 * needs ADB (the D-pad, Home, turning it off) is refused, saying so.
 */
object Device {
    /** Keys an app can press: media keys go to what's playing, volume to the TV. */
    private val MEDIA_KEYS = mapOf(
        "MEDIA_PLAY_PAUSE" to KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
        "MEDIA_PLAY" to KeyEvent.KEYCODE_MEDIA_PLAY,
        "MEDIA_PAUSE" to KeyEvent.KEYCODE_MEDIA_PAUSE,
        "MEDIA_STOP" to KeyEvent.KEYCODE_MEDIA_STOP,
        "MEDIA_NEXT" to KeyEvent.KEYCODE_MEDIA_NEXT,
        "MEDIA_PREVIOUS" to KeyEvent.KEYCODE_MEDIA_PREVIOUS,
        "MEDIA_REWIND" to KeyEvent.KEYCODE_MEDIA_REWIND,
        "MEDIA_FAST_FORWARD" to KeyEvent.KEYCODE_MEDIA_FAST_FORWARD,
    )
    private val VOLUME_KEYS = mapOf(
        "VOLUME_UP" to AudioManager.ADJUST_RAISE,
        "VOLUME_DOWN" to AudioManager.ADJUST_LOWER,
        "VOLUME_MUTE" to AudioManager.ADJUST_TOGGLE_MUTE,
    )
    val KEYS: Set<String> get() = MEDIA_KEYS.keys + VOLUME_KEYS.keys

    /** Notification access is allowed: other apps' media sessions can be read. */
    fun notificationAccess(context: Context): Boolean =
        Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners")
            ?.contains(ComponentName(context, MediaListener::class.java).flattenToString()) == true

    /** The TV's state, as Home Assistant reads it (GET /api/state). */
    fun state(context: Context): JSONObject {
        val audio = context.getSystemService(AudioManager::class.java)
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        return JSONObject()
            .put("screen_on", TvInfo.screenOn(context))
            .put("foreground_app", TvInfo.foregroundApp(context) ?: JSONObject.NULL)
            .put("uptime_ms", SystemClock.elapsedRealtime())
            .put(
                "volume",
                JSONObject()
                    .put("level", audio.getStreamVolume(AudioManager.STREAM_MUSIC))
                    .put("max", max)
                    .put("muted", audio.isStreamMute(AudioManager.STREAM_MUSIC)),
            )
            .put("sessions", sessions(context) ?: JSONObject.NULL)
            .put("overlay_permission", TvInfo.overlayAllowed(context))
            .put("usage_access", TvInfo.usageAccess(context))
            .put("notification_access", notificationAccess(context))
            .put("network_debugging", adbOn(context))
    }

    /** Media sessions, front first (null without notification access). */
    private fun sessions(context: Context): JSONArray? {
        if (!notificationAccess(context)) return null
        val manager = context.getSystemService(MediaSessionManager::class.java)
        val controllers = try {
            manager.getActiveSessions(ComponentName(context, MediaListener::class.java))
        } catch (e: SecurityException) {
            return null
        }
        return JSONArray().apply {
            controllers.forEach { controller ->
                val playback = controller.playbackState
                val meta = controller.metadata
                fun text(key: String): Any = meta?.getString(key)?.takeIf { it.isNotBlank() } ?: JSONObject.NULL
                put(
                    JSONObject()
                        .put("package", controller.packageName)
                        .put("state", playback?.state ?: PlaybackState.STATE_NONE)
                        .put("position_ms", playback?.position?.takeIf { it >= 0 } ?: JSONObject.NULL)
                        .put("updated_ms", playback?.lastPositionUpdateTime ?: JSONObject.NULL)
                        .put("speed", playback?.playbackSpeed?.toDouble() ?: 1.0)
                        .put("title", text(MediaMetadata.METADATA_KEY_TITLE))
                        .put(
                            "subtitle",
                            meta?.getString(MediaMetadata.METADATA_KEY_ARTIST)?.takeIf { it.isNotBlank() }
                                ?: text(MediaMetadata.METADATA_KEY_DISPLAY_SUBTITLE),
                        )
                        .put("description", text(MediaMetadata.METADATA_KEY_DISPLAY_DESCRIPTION)),
                )
            }
        }
    }

    /** Network debugging (ADB) is on: the switch, as the app can see it. */
    fun adbOn(context: Context): Boolean =
        Settings.Global.getInt(context.contentResolver, Settings.Global.ADB_ENABLED, 0) != 0

    /** The network, storage and memory (GET /api/diagnostics). */
    fun diagnostics(context: Context): JSONObject {
        val connectivity = context.getSystemService(ConnectivityManager::class.java)
        val caps = connectivity.getNetworkCapabilities(connectivity.activeNetwork)
        val connection = when {
            caps == null -> JSONObject.NULL
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            else -> JSONObject.NULL
        }
        @Suppress("DEPRECATION")
        val rssi = if (connection == "wifi") {
            context.applicationContext.getSystemService(WifiManager::class.java).connectionInfo?.rssi
                ?.takeIf { it in -110..-1 }
        } else {
            null
        }
        val stat = StatFs(Environment.getDataDirectory().path)
        val total = stat.totalBytes.coerceAtLeast(1)
        val memory = ActivityManager.MemoryInfo().also {
            context.getSystemService(ActivityManager::class.java).getMemoryInfo(it)
        }
        return JSONObject()
            .put("connection", connection)
            .put("wifi_signal", rssi ?: JSONObject.NULL)
            .put("storage_used", ((total - stat.availableBytes) * 100 / total).toInt())
            .put("storage_free_mb", stat.availableBytes / (1024 * 1024))
            .put("memory_free_mb", memory.availMem / (1024 * 1024))
            .put("memory_total_mb", memory.totalMem / (1024 * 1024))
    }

    /** Presses [key] if an app may; false if it needs ADB. */
    fun key(context: Context, key: String): Boolean {
        val audio = context.getSystemService(AudioManager::class.java)
        MEDIA_KEYS[key]?.let { code ->
            audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
            audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
            return true
        }
        VOLUME_KEYS[key]?.let { direction ->
            audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction, AudioManager.FLAG_SHOW_UI)
            return true
        }
        return false
    }

    /** The media volume, 0 to 1. */
    fun setVolume(context: Context, level: Double) {
        val audio = context.getSystemService(AudioManager::class.java)
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(level.coerceIn(0.0, 1.0) * max).toInt(), AudioManager.FLAG_SHOW_UI)
    }

    /** Opens an app by its launcher entry; false if there's none. */
    fun launch(context: Context, packageName: String): Boolean {
        val pm = context.packageManager
        val intent = pm.getLeanbackLaunchIntentForPackage(packageName)
            ?: pm.getLaunchIntentForPackage(packageName)
            ?: return false
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }

    /** Opens a link in the app that takes it. */
    fun openUrl(context: Context, url: String): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (e: android.content.ActivityNotFoundException) {
        false
    }

    /** Switches to an HDMI input, through the TV's own input app. */
    fun selectInput(context: Context, id: String): Boolean = try {
        context.startActivity(
            Intent(Intent.ACTION_VIEW, TvContract.buildChannelUriForPassthroughInput(id))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        true
    } catch (e: android.content.ActivityNotFoundException) {
        false
    }
}
