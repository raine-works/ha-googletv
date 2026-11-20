package com.raineworks.tvbridge

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import android.view.View
import androidx.core.content.res.ResourcesCompat

/**
 * The look: the Home Assistant dashboards' dark theme (shadcn's neutral
 * tokens): near-black surfaces, hairline borders, Poppins, a 10 dp radius.
 */
object Theme {
    val BACKGROUND = Color.parseColor("#0A0A0A")
    val CARD = Color.parseColor("#171717")
    // The sections' rail, a step above the background
    val RAIL = Color.parseColor("#111111")
    val MUTED = Color.parseColor("#262626")
    // A switch that's off: it shows on a card and on a focused row alike
    val SWITCH_OFF = Color.parseColor("#404040")
    val FOREGROUND = Color.parseColor("#FAFAFA")
    val MUTED_FOREGROUND = Color.parseColor("#A1A1A1")
    val PRIMARY = Color.parseColor("#E5E5E5")
    val PRIMARY_FOREGROUND = Color.parseColor("#171717")
    val BORDER = Color.argb(26, 255, 255, 255)
    val RING = Color.parseColor("#737373")
    val INFO = Color.parseColor("#4693F1")
    val SUCCESS = Color.parseColor("#009956")
    val WARNING = Color.parseColor("#F7A224")
    val DESTRUCTIVE = Color.parseColor("#FF6467")

    const val RADIUS_DP = 10

    private var regular: Typeface? = null
    private var medium: Typeface? = null
    private var semibold: Typeface? = null

    fun regular(context: Context): Typeface =
        regular ?: (ResourcesCompat.getFont(context, R.font.poppins_regular) ?: Typeface.DEFAULT)
            .also { regular = it }

    fun medium(context: Context): Typeface =
        medium ?: (ResourcesCompat.getFont(context, R.font.poppins_medium) ?: Typeface.DEFAULT)
            .also { medium = it }

    fun semibold(context: Context): Typeface =
        semibold ?: (ResourcesCompat.getFont(context, R.font.poppins_semibold) ?: Typeface.DEFAULT_BOLD)
            .also { semibold = it }

    fun dp(context: Context, value: Number): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), context.resources.displayMetrics,
    ).toInt()

    /** A rounded surface with a hairline border. */
    fun surface(context: Context, fill: Int, radiusDp: Int = RADIUS_DP, stroke: Int = BORDER): GradientDrawable =
        GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(context, radiusDp).toFloat()
            setStroke(dp(context, 1), stroke)
        }

    /** The space between a control and its focus ring. */
    const val FOCUS_GAP_DP = 4

    /**
     * A control's background: [fill] at rest; when the remote's focus is on
     * it, a ring a few dp outside it (the card showing between), so it shows
     * on light and dark controls alike. The control draws inset by the gap:
     * give it that much more padding.
     */
    fun focusable(context: Context, fill: Int, radiusDp: Int = RADIUS_DP, stroke: Int = BORDER): Drawable {
        val gap = dp(context, FOCUS_GAP_DP)
        val radius = dp(context, radiusDp).toFloat()
        fun body(color: Int, border: Int) = GradientDrawable().apply {
            setColor(color)
            cornerRadius = radius
            setStroke(dp(context, 1), border)
        }
        val rest = LayerDrawable(arrayOf(body(fill, stroke))).apply {
            setLayerInset(0, gap, gap, gap, gap)
        }
        val ring = GradientDrawable().apply {
            setColor(Color.TRANSPARENT)
            cornerRadius = radius + gap
            setStroke(dp(context, 2), FOREGROUND)
        }
        val focusedFill = if (fill == Color.TRANSPARENT) MUTED else fill
        val focused = LayerDrawable(arrayOf(ring, body(focusedFill, if (fill == Color.TRANSPARENT) BORDER else stroke))).apply {
            setLayerInset(1, gap, gap, gap, gap)
        }
        return StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), focused)
            addState(intArrayOf(android.R.attr.state_pressed), focused)
            addState(intArrayOf(), rest)
        }
    }

    /** Grows a little while focused: easy to spot from the couch. */
    fun lift(view: View, scale: Float = 1.04f) {
        view.setOnFocusChangeListener { v, focused ->
            v.animate().scaleX(if (focused) scale else 1f).scaleY(if (focused) scale else 1f)
                .setDuration(120).start()
        }
    }

    fun blend(color: Int, with: Int, amount: Float): Int = Color.rgb(
        (Color.red(color) * (1 - amount) + Color.red(with) * amount).toInt(),
        (Color.green(color) * (1 - amount) + Color.green(with) * amount).toInt(),
        (Color.blue(color) * (1 - amount) + Color.blue(with) * amount).toInt(),
    )

    fun withAlpha(color: Int, alpha: Int): Int =
        Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color))
}
