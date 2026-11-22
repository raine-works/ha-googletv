package com.raineworks.tvbridge

import android.content.Context
import android.view.View
import android.widget.ImageView

/** The logo: the raineworks mark in its peach-to-teal gradient, nothing of Google's. */
object Brand {
    /** The logo; the caller's layout sizes it. */
    fun logo(context: Context): View =
        ImageView(context).apply { setImageResource(R.drawable.raineworks_mark) }
}
