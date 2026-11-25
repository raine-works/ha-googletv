package com.raineworks.tvbridge

import android.content.Context
import android.view.View
import android.widget.ImageView

/** The logo: Google TV's icon, as the launcher and the integration show it (brand/art.py). */
object Brand {
    /** The logo; the caller's layout sizes it. */
    fun logo(context: Context): View =
        ImageView(context).apply { setImageResource(R.drawable.logo) }
}
