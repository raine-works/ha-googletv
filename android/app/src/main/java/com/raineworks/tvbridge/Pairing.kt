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
