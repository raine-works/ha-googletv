package com.raineworks.tvbridge

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.media.tv.TvInputManager
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.provider.Settings

/** What the bridge can see of the TV without ADB. */
object TvInfo {
    /** Developer options are on (the build number was selected seven times). */
    fun developerOptions(context: Context): Boolean =
        Settings.Global.getInt(context.contentResolver, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) != 0

    /**
     * Network debugging is on: ADB answers on its port, as Home Assistant
     * will connect to it. It blocks for a moment: not on the main thread.
     */
    fun networkDebugging(): Boolean = try {
        java.net.Socket().use { it.connect(java.net.InetSocketAddress("127.0.0.1", ADB_PORT), 500) }
        true
    } catch (e: java.io.IOException) {
        false
    }

    private const val ADB_PORT = 5555

    data class App(val packageName: String, val name: String)
    data class Input(val id: String, val name: String)

    /** The launcher's apps, by name. */
    fun apps(context: Context): List<App> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LEANBACK_LAUNCHER)
        return pm.queryIntentActivities(intent, 0)
            .map { App(it.activityInfo.packageName, it.loadLabel(pm).toString()) }
            .distinctBy { it.packageName }
            .sortedBy { it.name.lowercase() }
    }

    /** The TV's HDMI and other external inputs, by the names given on the TV. */
    fun inputs(context: Context): List<Input> {
        val manager = context.getSystemService(Context.TV_INPUT_SERVICE) as? TvInputManager
            ?: return emptyList()
        return try {
            manager.tvInputList
                .filter { it.isPassthroughInput && !it.isHidden(context) }
                .map {
                    val name = it.loadCustomLabel(context)?.toString()?.takeIf { l -> l.isNotBlank() }
                        ?: it.loadLabel(context).toString()
                    Input(it.id, name)
                }
        } catch (e: SecurityException) {
            emptyList()
        }
    }

    fun screenOn(context: Context): Boolean =
        (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive

    /** Whether "Usage access" is allowed (the app in front, for the rules). */
    fun usageAccess(context: Context): Boolean {
        val ops = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ops.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName,
            )
        } else {
            @Suppress("DEPRECATION")
            ops.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName,
            )
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun overlayAllowed(context: Context): Boolean = Settings.canDrawOverlays(context)

    /** The app in front (its package), when usage access is allowed. */
    fun foregroundApp(context: Context): String? {
        if (!usageAccess(context)) return null
        val usage = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        for (window in longArrayOf(60 * 60 * 1000L, 24 * 60 * 60 * 1000L)) {
            val events = usage.queryEvents(now - window, now)
            val event = UsageEvents.Event()
            var last: String? = null
            while (events.hasNextEvent()) {
                events.getNextEvent(event)
                @Suppress("DEPRECATION")
                if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    last = event.packageName
                }
            }
            if (last != null) return last
        }
        return null
    }

    /** The TV's own name (Settings → Device name), else its model. */
    fun deviceName(context: Context): String =
        Settings.Global.getString(context.contentResolver, "device_name")
            ?.takeIf { it.isNotBlank() } ?: Build.MODEL
}
