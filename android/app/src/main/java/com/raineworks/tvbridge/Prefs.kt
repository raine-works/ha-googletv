package com.raineworks.tvbridge

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.SecureRandom

/**
 * What the bridge keeps: Home Assistant's tokens, the notification rules, the apps it hides.
 *
 * Home Assistant keeps a copy of the rules and gives them back when [dataId]
 * changes: the app's data went (reinstalled, or its data cleared).
 */
class Prefs(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences("bridge", Context.MODE_PRIVATE)

    /** Tokens Home Assistant paired with (one per connection). */
    val tokens: Set<String>
        get() = prefs.getStringSet(KEY_TOKENS, emptySet())!!.toSet()

    fun newToken(): String = synchronized(LOCK) {
        val token = Access.newToken(random)
        prefs.edit().putStringSet(KEY_TOKENS, tokens + token).apply()
        token
    }

    /** Whether a request carries a token Home Assistant paired with. */
    fun isPaired(token: String?): Boolean = Access.isPaired(token, tokens)

    fun forget(token: String) = synchronized(LOCK) {
        prefs.edit().putStringSet(KEY_TOKENS, tokens - token).apply()
    }

    fun forgetAll() {
        prefs.edit().remove(KEY_TOKENS).remove(KEY_HA_TOKEN).apply()
    }

    /** The integration's version, as Home Assistant last said. */
    var clientVersion: String
        get() = prefs.getString(KEY_CLIENT_VERSION, "")!!
        set(value) = prefs.edit().putString(KEY_CLIENT_VERSION, value).apply()

    /**
     * The TV's own Home Assistant user's token (read-only unless allowed
     * more), which the app signs in to Home Assistant's websocket with to
     * open a camera over WebRTC. Home Assistant gives it once.
     */
    var homeAssistantToken: String
        get() = prefs.getString(KEY_HA_TOKEN, "")!!
        set(value) = prefs.edit().putString(KEY_HA_TOKEN, value).apply()

    /** Home Assistant also reaches the TV over ADB (its extra features). */
    var clientAdb: Boolean
        get() = prefs.getBoolean(KEY_CLIENT_ADB, false)
        set(value) = prefs.edit().putBoolean(KEY_CLIENT_ADB, value).apply()

    /**
     * This copy of the app's data: made at random the first time it's asked
     * for, so it's new after a reinstall or a cleared data. Says nothing
     * about the TV or its owner.
     */
    val dataId: String
        get() = synchronized(LOCK) {
            prefs.getString(KEY_DATA_ID, null) ?: java.util.UUID.randomUUID().toString().also {
                // commit, not apply: an update installed right after can't lose it
                prefs.edit().putString(KEY_DATA_ID, it).commit()
            }
        }

    /** Pop-ups at all: off, every notification is handled as blocked ([whenBlocked]). */
    var popupsEnabled: Boolean
        get() = prefs.getBoolean(KEY_POPUPS, true)
        set(value) = prefs.edit().putBoolean(KEY_POPUPS, value).apply()

    /** Apps (packages) that pop-ups don't show over. */
    var blockedApps: Set<String>
        get() = prefs.getStringSet(KEY_BLOCKED_APPS, emptySet())!!.toSet()
        set(value) = prefs.edit().putStringSet(KEY_BLOCKED_APPS, value).apply()

    /** Apps (packages) Home Assistant leaves out: its app list, its buttons. */
    var hiddenApps: Set<String>
        get() = prefs.getStringSet(KEY_HIDDEN_APPS, emptySet())!!.toSet()
        set(value) = prefs.edit().putStringSet(KEY_HIDDEN_APPS, value).apply()

    /** HDMI inputs (TV input ids) Home Assistant leaves out: its source list, its Input. */
    var hiddenInputs: Set<String>
        get() = prefs.getStringSet(KEY_HIDDEN_INPUTS, emptySet())!!.toSet()
        set(value) = prefs.edit().putStringSet(KEY_HIDDEN_INPUTS, value).apply()

    /** HDMI inputs (TV input ids) that pop-ups don't show over. */
    var blockedInputs: Set<String>
        get() = prefs.getStringSet(KEY_BLOCKED_INPUTS, emptySet())!!.toSet()
        set(value) = prefs.edit().putStringSet(KEY_BLOCKED_INPUTS, value).apply()

    /** Pop-ups' size when a notification doesn't say: compact, small, medium, large. */
    var defaultSize: String
        get() = prefs.getString(KEY_DEFAULT_SIZE, "small")!!
        set(value) = prefs.edit().putString(KEY_DEFAULT_SIZE, value).apply()

    /** Pop-ups' place on screen when a notification doesn't say. */
    var defaultPosition: String
        get() = prefs.getString(KEY_DEFAULT_POSITION, "top_right")!!
        set(value) = prefs.edit().putString(KEY_DEFAULT_POSITION, value).apply()

    /** A blocked pop-up goes to the notification panel ("panel") or nowhere ("drop"). */
    var whenBlocked: String
        get() = prefs.getString(KEY_WHEN_BLOCKED, WHEN_BLOCKED_PANEL)!!
        set(value) = prefs.edit().putString(KEY_WHEN_BLOCKED, value).apply()

    /** The rules and the hidden apps, as the API and its events say them. */
    fun rules(): JSONObject = JSONObject()
        .put("popups", popupsEnabled)
        .put("hidden_apps", JSONArray(hiddenApps.sorted()))
        .put("blocked_apps", JSONArray(blockedApps.sorted()))
        .put("hidden_inputs", JSONArray(hiddenInputs.sorted()))
        .put("blocked_inputs", JSONArray(blockedInputs.sorted()))
        .put("when_blocked", whenBlocked)
        .put("default_size", defaultSize)
        .put("default_position", defaultPosition)

    companion object {
        // Pairing and unpairing change the token set one at a time
        private val LOCK = Any()
        private const val KEY_CLIENT_VERSION = "client_version"
        private const val KEY_CLIENT_ADB = "client_adb"
        private const val KEY_HA_TOKEN = "home_assistant_token"
        const val WHEN_BLOCKED_PANEL = "panel"
        const val WHEN_BLOCKED_DROP = "drop"
        private const val KEY_TOKENS = "tokens"
        private const val KEY_DATA_ID = "data_id"
        private const val KEY_POPUPS = "popups"
        private const val KEY_BLOCKED_APPS = "blocked_apps"
        private const val KEY_HIDDEN_APPS = "hidden_apps"
        private const val KEY_HIDDEN_INPUTS = "hidden_inputs"
        private const val KEY_BLOCKED_INPUTS = "blocked_inputs"
        private const val KEY_WHEN_BLOCKED = "when_blocked"
        private const val KEY_DEFAULT_SIZE = "default_size"
        private const val KEY_DEFAULT_POSITION = "default_position"
        private val random = SecureRandom()
    }
}
