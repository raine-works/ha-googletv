package com.raineworks.tvbridge

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import androidx.core.content.res.ResourcesCompat

/**
 * The look: the Home Assistant dashboards' dark theme (shadcn's neutral
 * tokens): near-black surfaces, hairline borders, Poppins, a 10 dp radius.
 */
object Theme {
    val BACKGROUND = Color.parseColor("#0A0A0A")
    val CARD = Color.parseColor("#171717")
    val MUTED = Color.parseColor("#262626")
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

    /**
     * A control's background: [fill] at rest; a lighter fill and a ring when
     * the remote's focus is on it (TVs have no hover or touch).
     */
    fun focusable(context: Context, fill: Int, radiusDp: Int = RADIUS_DP, stroke: Int = BORDER): Drawable {
        val focused = GradientDrawable().apply {
            setColor(if (fill == Color.TRANSPARENT) MUTED else blend(fill, Color.WHITE, 0.08f))
            cornerRadius = dp(context, radiusDp).toFloat()
            setStroke(dp(context, 2), FOREGROUND)
        }
        val states = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), focused)
            addState(intArrayOf(), surface(context, fill, radiusDp, stroke))
        }
        return RippleDrawable(ColorStateList.valueOf(Color.argb(40, 255, 255, 255)), states, null)
    }

    fun blend(color: Int, with: Int, amount: Float): Int = Color.rgb(
        (Color.red(color) * (1 - amount) + Color.red(with) * amount).toInt(),
        (Color.green(color) * (1 - amount) + Color.green(with) * amount).toInt(),
        (Color.blue(color) * (1 - amount) + Color.blue(with) * amount).toInt(),
    )

    fun withAlpha(color: Int, alpha: Int): Int =
        Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color))
}
