package com.raineworks.tvbridge

import android.content.Context
import java.io.File
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
                imageUrl = null, videoUrl = null,
                // The app's own screen asks already when it's in front: no pop-up over it
                mode = if (MainActivity.inFront) NotificationRequest.MODE_PANEL else NotificationRequest.MODE_BOTH,
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

    private val random = SecureRandom()

    // The codes, their expiry and the wrong-codes lock (PairingCodes)
    private val codes = PairingCodes()

    /** One pairing started a second: no flood of codes on screen, or of pairings evicting a real one. */
    fun mayStart(): Boolean = codes.mayStart()

    /** Pairing is locked a while after too many wrong codes (a guess at every code takes ~1M). */
    fun locked(): Boolean = codes.locked()

    /** A new pairing: its id; its code shown on screen, or written for ADB. */
    @Synchronized
    fun start(context: Context, via: String): String {
        val (id, code) = codes.start()
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
        if (!codes.finish(id, code)) return null
        codeFile(context)?.delete()
        Overlay.get(context).dismiss(Overlay.PAIRING_TAG)
        Notifications.cancelPairingCode(context)
        return Prefs(context).newToken()
    }

    private fun codeFile(context: Context): File? =
        context.getExternalFilesDir(null)?.let { File(it, "pairing_code") }
}
