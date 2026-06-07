# Feature Specification: Synchronized "Actuation Ripple" Animation

### 1. Feature Overview & Objective

The goal of this feature is to bridge the gap between the digital interface and the physical hardware. When a user selects a note, the physical plate vibrates for a precise, predetermined amount of time.

To provide immediate, organic visual feedback during this actuation phase, the UI will display a single, expanding ripple effect originating from the center of the screen. This effect serves as a visual proxy for the physical vibration, starting the moment the plate begins to vibrate and vanishing the exact millisecond the plate stops. It should feel like a water droplet hitting a still pond—elegant, discrete, and physically grounded.

### 2. Visual Design & Aesthetics

The ripple must be a subtle enhancement, not a distraction. It should enrich the environment without cluttering the dashboard or making text difficult to read.

* **Shape & Style:** A perfect, unfilled circle (an outline/stroke only).
* **Color & Weight:** The stroke should use the UI's primary accent color (the previous generated color note), drawn with a thin, crisp line weight (e.g., 2 pixels).
* **Layering (Z-Ordering):** This is critical. The ripple must sit in the "mid-ground" of the interface:
* **ABOVE** the continuous background waveforms.
* **BELOW** the central note wheel, text elements, status indicators, and buttons.


* **Opacity:** The ripple must be highly transparent. Even at its most visible state, it should not exceed roughly 40% maximum opacity so it acts as a "ghost ring" rather than a solid object.

### 3. Behavior & Animation Dynamics

The movement of the ripple must mimic physical wave propagation. A strictly linear expansion (moving at a constant speed) will look artificial and robotic.

* **Origin Point:** The animation must originate precisely from the center coordinates of the central note wheel.
* **Starting State:** The ripple begins with a radius exactly matching the outer edge of the note wheel.
* **Expansion (Easing):** As the ripple travels outward, its expansion speed must decelerate over time. It should burst outward quickly at the moment of impact and gradually slow down as it approaches its maximum radius.
* **Fade-Out:** As the ripple expands, it must simultaneously fade away. The opacity should decay smoothly from its starting transparency down to completely invisible (0% opacity) by the time the animation finishes.

### 4. Trigger & Synchronization Logic

The timing of this animation is its most important characteristic. It must be perfectly slaved to the hardware actuation data.

* **The Source of Truth:** The total duration of the ripple animation must be dynamically read from the `time` parameter associated with the selected note in the `master_symbols.json` file.
* **The Trigger:** The ripple begins the exact moment the user input is confirmed and the wheel animation initiates (which coincides with the physical plate receiving the signal).
* **The Conclusion:** The ripple must complete its maximum expansion and reach 0% opacity at the exact millisecond the physical plate's vibration time concludes.

### 5. System Constraints & Edge Cases

* **Single Instance State:** Because the UI actively blocks new user inputs while the plate is vibrating (during the wheel animation phase), there is no scenario where multiple ripples should overlap. The system only needs to render and track a single ripple animation at any given time.
* **Performance:** The animation must be lightweight. It should be rendered using standard 2D drawing primitives tied to the existing UI refresh cycle to ensure no frame drops or stuttering occur on the dashboard.
