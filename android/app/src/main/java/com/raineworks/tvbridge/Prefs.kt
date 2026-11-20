package com.raineworks.tvbridge

import android.content.Context
import android.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom

/** What the bridge keeps: Home Assistant's tokens and the notification rules. */
class Prefs(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences("bridge", Context.MODE_PRIVATE)

    /** Tokens Home Assistant paired with (one per connection). */
    val tokens: Set<String>
        get() = prefs.getStringSet(KEY_TOKENS, emptySet())!!.toSet()

    fun newToken(): String = synchronized(LOCK) {
        val bytes = ByteArray(32).also { random.nextBytes(it) }
        val token = Base64.encodeToString(
            bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP,
        )
        prefs.edit().putStringSet(KEY_TOKENS, tokens + token).apply()
        token
    }

    /** Whether a request carries a token Home Assistant paired with. */
    fun isPaired(token: String?): Boolean {
        if (token.isNullOrEmpty()) return false
        val given = token.toByteArray()
        // Compared in constant time
        return tokens.any { MessageDigest.isEqual(it.toByteArray(), given) }
    }

    fun forget(token: String) = synchronized(LOCK) {
        prefs.edit().putStringSet(KEY_TOKENS, tokens - token).apply()
    }

    fun forgetAll() {
        prefs.edit().remove(KEY_TOKENS).apply()
    }

    /** Apps (packages) that pop-ups don't show over. */
    var blockedApps: Set<String>
        get() = prefs.getStringSet(KEY_BLOCKED_APPS, emptySet())!!.toSet()
        set(value) = prefs.edit().putStringSet(KEY_BLOCKED_APPS, value).apply()

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

    companion object {
        // Pairing and unpairing change the token set one at a time
        private val LOCK = Any()
        const val WHEN_BLOCKED_PANEL = "panel"
        const val WHEN_BLOCKED_DROP = "drop"
        private const val KEY_TOKENS = "tokens"
        private const val KEY_BLOCKED_APPS = "blocked_apps"
        private const val KEY_BLOCKED_INPUTS = "blocked_inputs"
        private const val KEY_WHEN_BLOCKED = "when_blocked"
        private const val KEY_DEFAULT_SIZE = "default_size"
        private const val KEY_DEFAULT_POSITION = "default_position"
        private val random = SecureRandom()
    }
}
