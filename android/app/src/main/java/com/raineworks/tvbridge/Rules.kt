package com.raineworks.tvbridge

/**
 * Whether a pop-up may show over what's on screen: the pop-ups switch (all
 * of them, off while Home Assistant's movie mode is on, say), then the apps'
 * and inputs' own switches. Pure, so a JVM unit test checks it.
 */
object Rules {
    /** `blocked_by` when the pop-ups switch is off: every pop-up is kept off the screen. */
    const val ALL = "all"

    /**
     * The rule that keeps a pop-up off the screen now, or null when it may
     * show: [ALL] when pop-ups are switched off, else "input:<id>" for a
     * blocked input on screen, else "app:<package>" for a blocked app in front.
     */
    fun blockingRule(
        popups: Boolean,
        blockedApps: Set<String>,
        blockedInputs: Set<String>,
        app: String?,
        input: String?,
    ): String? {
        if (!popups) return ALL
        if (input != null && input in blockedInputs) return "input:$input"
        if (app != null && app in blockedApps) return "app:$app"
        return null
    }

    /**
     * The pop-ups switch from a POST /api/rules body's `popups`: null when it
     * isn't there; a JSON boolean only (a string "false" would read as on).
     *
     * @throws IllegalArgumentException when it's there but not a boolean.
     */
    fun popups(value: Any?): Boolean? = when (value) {
        null -> null
        is Boolean -> value
        else -> throw IllegalArgumentException("popups must be true or false")
    }
}
