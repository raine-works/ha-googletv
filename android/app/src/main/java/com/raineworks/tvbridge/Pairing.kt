package com.raineworks.tvbridge

import android.content.Context
import java.io.File
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Pairing Home Assistant: it asks for a code, the TV shows it (or, when the
 * integration has ADB, writes it where only ADB can read it), and Home
 * Assistant sends it back for a token.
 */
object Pairing {
    const val VIA_SCREEN = "screen"
    const val VIA_ADB = "adb"
    // The TV asks "Allow Home Assistant to connect?": no code at all
    const val VIA_CONFIRM = "confirm"
    private const val CONFIRM_TTL_MS = 2 * 60 * 1000L

    /** A request to connect, waiting for its answer on the TV. */
    class Request(val id: String, val name: String, val address: String, val expires: Long) {
        @Volatile var answer: Boolean? = null
        @Volatile var token: String? = null
    }

    /** The one request waiting for an answer, if any (read by the app's screen). */
    @Volatile
    var request: Request? = null
        private set

    /** Asks on the TV whether [name] at [address] may connect; its pairing id. */
    @Synchronized
    fun startConfirm(context: Context, name: String, address: String): String {
        val id = ByteArray(12).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
        request = Request(id, name.take(60), address, System.currentTimeMillis() + CONFIRM_TTL_MS)
        val ask = context.getString(R.string.pair_ask_title)
        Notifier.handle(
            context,
            NotificationRequest(
                title = ask, message = context.getString(R.string.pair_ask_text, name.take(60), address),
                imageUrl = null, videoUrl = null, mode = NotificationRequest.MODE_BOTH,
                position = "center", durationS = 0, size = "medium", color = null, mute = true,
                ignoreRules = true, whenBlocked = null, tag = Actions.PAIR_TAG, icon = "mdi:home-assistant",
                actions = listOf(
                    NotificationRequest.Action(Actions.ALLOW, context.getString(R.string.pair_allow)),
                    NotificationRequest.Action(Actions.DENY, context.getString(R.string.pair_deny)),
                ),
                contextApp = null, contextInput = null,
            ),
        )
        return id
    }

    /** The answer to the request waiting: a token for Home Assistant, or no. */
    fun answer(context: Context, allow: Boolean) {
        synchronized(this) {
            val pending = request ?: return
            if (pending.answer != null) return
            pending.answer = allow
            if (allow) pending.token = Prefs(context).newToken()
        }
        Notifier.dismiss(context, Actions.PAIR_TAG)
    }

    /** How a request stands: pending, allowed (with its token, given once), denied or unknown. */
    @Synchronized
    fun status(context: Context, id: String): org.json.JSONObject {
        val pending = request?.takeIf { it.id == id }
            ?: return org.json.JSONObject().put("status", "unknown")
        if (pending.answer == null && System.currentTimeMillis() > pending.expires) {
            request = null
            Notifier.dismiss(context, Actions.PAIR_TAG)
            return org.json.JSONObject().put("status", "expired")
        }
        return when (pending.answer) {
            null -> org.json.JSONObject().put("status", "pending")
            false -> org.json.JSONObject().put("status", "denied").also { request = null }
            true -> org.json.JSONObject().put("status", "allowed").put("token", pending.token).also { request = null }
        }
    }

    private const val CODE_TTL_MS = 5 * 60 * 1000L
    private const val MAX_ATTEMPTS = 5
    private const val MAX_PENDING = 4
    // Wrong codes, across pairings: this many in the window locks pairing
    private const val MAX_FAILURES = 10
    private const val FAILURE_WINDOW_MS = 10 * 60 * 1000L
    private const val LOCKOUT_MS = 10 * 60 * 1000L
    private val random = SecureRandom()

    private data class Pending(val code: String, val expires: Long, var attempts: Int)

    private val pending = LinkedHashMap<String, Pending>()
    private val failures = ArrayDeque<Long>()
    private var lockedUntil = 0L

    private var lastStart = 0L

    /** One pairing started a second: no flood of codes on screen, or of pairings evicting a real one. */
    @Synchronized
    fun mayStart(): Boolean {
        val now = System.currentTimeMillis()
        if (now - lastStart < 1000) return false
        lastStart = now
        return true
    }

    /** Pairing is locked a while after too many wrong codes (a guess at every code takes ~1M). */
    @Synchronized
    fun locked(): Boolean = System.currentTimeMillis() < lockedUntil

    /** A new pairing: its id; its code shown on screen, or written for ADB. */
    @Synchronized
    fun start(context: Context, via: String): String {
        val now = System.currentTimeMillis()
        check(now >= lockedUntil) { "Too many wrong codes: try again later" }
        pending.entries.removeAll { it.value.expires < now }
        while (pending.size >= MAX_PENDING) pending.remove(pending.keys.first())
        val id = ByteArray(12).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val code = "%06d".format(random.nextInt(1_000_000))
        pending[id] = Pending(code, now + CODE_TTL_MS, 0)
        if (via == VIA_ADB) {
            // The app's own external folder: ADB (the shell) can read it, other
            // apps and the network can't
            codeFile(context)?.writeText("$id $code\n")
        } else if (TvInfo.overlayAllowed(context)) {
            Overlay.get(context).showPairingCode(code)
        } else {
            // No pop-ups allowed: the notification panel
            Notifications.postPairingCode(context, code)
        }
        return id
    }

    /** A token, when the code is right; null otherwise. */
    @Synchronized
    fun finish(context: Context, id: String, code: String): String? {
        val entry = pending[id] ?: return null
        if (entry.expires < System.currentTimeMillis() || entry.attempts >= MAX_ATTEMPTS) {
            pending.remove(id)
            return null
        }
        entry.attempts++
        if (!MessageDigest.isEqual(entry.code.toByteArray(), code.trim().toByteArray())) {
            val now = System.currentTimeMillis()
            failures.addLast(now)
            while (failures.isNotEmpty() && failures.first() < now - FAILURE_WINDOW_MS) failures.removeFirst()
            if (failures.size >= MAX_FAILURES) {
                lockedUntil = now + LOCKOUT_MS
                failures.clear()
                pending.clear()
            }
            return null
        }
        pending.remove(id)
        codeFile(context)?.delete()
        Overlay.get(context).dismiss(Overlay.PAIRING_TAG)
        Notifications.cancelPairingCode(context)
        return Prefs(context).newToken()
    }

    private fun codeFile(context: Context): File? =
        context.getExternalFilesDir(null)?.let { File(it, "pairing_code") }
}
