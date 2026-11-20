package com.raineworks.tvbridge

import android.content.Context
import android.graphics.Typeface

/**
 * Home Assistant's icons (Material Design Icons 7.4.47, the version Home
 * Assistant's frontend uses): "mdi:doorbell" as a glyph of the bundled font.
 */
object Icons {
    @Volatile
    private var codepoints: Map<String, Int>? = null

    @Volatile
    private var typeface: Typeface? = null

    fun typeface(context: Context): Typeface =
        typeface ?: synchronized(this) {
            typeface ?: Typeface.createFromAsset(context.assets, "mdi/materialdesignicons.ttf")
                .also { typeface = it }
        }

    /** The glyph for "mdi:<name>" (or "<name>"), or null for a name it doesn't know. */
    fun glyph(context: Context, icon: String): String? {
        val name = icon.removePrefix("mdi:")
        val map = codepoints ?: synchronized(this) {
            codepoints ?: context.assets.open("mdi/codepoints.txt").bufferedReader().useLines { lines ->
                lines.mapNotNull { line ->
                    val parts = line.split(' ')
                    if (parts.size == 2) parts[0] to parts[1].toInt(16) else null
                }.toMap()
            }.also { codepoints = it }
        }
        return map[name]?.let { String(Character.toChars(it)) }
    }

    fun isMdi(icon: String): Boolean = icon.startsWith("mdi:")
}
