---
# Placeholder: a scene with choices, free text, a second part, effects and a secret.
# A nod to an old favourite's mountaintop trial, where the fight is won by not fighting.
id: mirror_trial
title: The Mirror Trial
when: enter_room
if: floor >= 2; first_visit; not in_combat; chance 25%
once: profile
voice: exact
secret: yes
hint: Not every fight is won by fighting.
sprite: mirror
---
A tall mirror stands where a wall should be, its frame carved with tired angels. Your reflection
draws its weapon a heartbeat before you do, and waits.

* Attack your reflection (attack, fight, strike, swing, hit, smash, break)
  -> Glass explodes outward. Your reflection's blade was real enough, and so is the cut it leaves.
     [hp -6] [flag mirror_broken]
* Lower your weapon (lower, sheathe, put down, put away, yield, refuse, wait, surrender)
  -> Your reflection hesitates. Then, slowly, it lowers its blade too, and bows. [goto bow]
* (anything else)
  -> It copies you exactly. A little too exactly. A thin red line opens on your cheek, then on its.
     [hp -2]

## bow
The glass clouds over. When it clears, your reflection is gone, and the mirror shows this room as
it was before the dark came: candlelit, warm, and full of people who are long gone.

* Step through (step, enter, go through, go in, walk through)
  -> Warmth. Light. For one long breath you are someone kinder than you have been.
     [heal] [fate +1] [mark mirror_unbroken] [secret]
* Leave it be (leave, back away, turn away, walk away, no)
  -> You let the moment go. Behind you, the mirror sighs, and goes dark for good.
     [souls 15] [mark mirror_declined] [secret]
