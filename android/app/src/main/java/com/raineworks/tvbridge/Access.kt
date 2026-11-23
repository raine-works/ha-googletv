package com.raineworks.tvbridge

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/**
 * The API's bearer-token checks, without Android, so they're unit tested
 * (AccessTest). [Prefs] keeps the tokens; [ApiServer] answers 401 to any
 * request [isPaired] refuses.
 */
object Access {
    /**
     * The token an "Authorization" header carries: what follows "Bearer ",
     * trimmed; null when there's no header.
     */
    fun bearer(authorization: String?): String? = authorization?.removePrefix("Bearer ")?.trim()

    /**
     * Whether [token] is one of [tokens] (those Home Assistant paired with).
     * A missing or empty token never is; each is compared in constant time.
     */
    fun isPaired(token: String?, tokens: Set<String>): Boolean {
        if (token.isNullOrEmpty()) return false
        val given = token.toByteArray()
        return tokens.any { MessageDigest.isEqual(it.toByteArray(), given) }
    }

    /** A new token: 32 random bytes, base64url without padding (43 characters). */
    fun newToken(random: SecureRandom): String {
        val bytes = ByteArray(32).also { random.nextBytes(it) }
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }
}
