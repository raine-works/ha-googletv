package com.raineworks.tvbridge

import android.content.Context
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView

/** The logo: the raineworks mark, Google TV's icon in its corner. */
object Brand {
    /** The logo [sizeDp] across, its badge over the bottom-right edge. */
    fun logo(context: Context, sizeDp: Int): View {
        val badge = sizeDp * 9 / 20
        return FrameLayout(context).apply {
            clipChildren = false
            addView(
                ImageView(context).apply { setImageResource(R.drawable.raineworks_mark) },
                FrameLayout.LayoutParams(Theme.dp(context, sizeDp), Theme.dp(context, sizeDp), Gravity.TOP or Gravity.START),
            )
            addView(
                ImageView(context).apply {
                    setImageResource(R.drawable.logo_gtv)
                    val pad = Theme.dp(context, 2)
                    setPadding(pad, pad, pad, pad)
                    background = GradientDrawable().apply {
                        setColor(Theme.RAIL)
                        cornerRadius = Theme.dp(context, 6).toFloat()
                    }
                },
                FrameLayout.LayoutParams(Theme.dp(context, badge), Theme.dp(context, badge), Gravity.BOTTOM or Gravity.END),
            )
        }
    }
}
