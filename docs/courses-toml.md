# `courses.toml`

The schedule file. It lives in your data root, next to the course folders, and the app re-reads it whenever it changes. Write it by hand once per term.

```toml
timezone = "Europe/Istanbul"   # times below are local times in this zone
term_end = "2026-12-11"        # no classes after this date

# Days or parts of days without classes (holidays, strikes).
[[closures]]
date = "2026-10-29"            # whole day

[[closures]]
date = "2026-10-28"
start = "13:00"                # from 13:00 to the end of the day

[[courses]]
code = "CS 101"                # used everywhere to refer to the course
name = "Algorithms"
folder = "CS101 Algorithms"    # folder inside the data root
aliases = ["101", "algo"]      # what you might type in the input bar
language = "en"                # language the lecture is given in (for transcription)
moodle_id = 12345              # optional, enables Moodle sync
syllabus = "slides/syllabus.pdf"   # optional, relative to the course folder

  [[courses.slots]]            # one block per weekly class
  day = "tue"                  # mon tue wed thu fri sat sun
  start = "09:00"
  end = "11:00"
  kind = "lecture"             # lecture, ps, lab ... free text
  location = "Room 101"        # optional
  first = "2026-09-29"         # optional, first week this slot is held
  skip = ["2026-11-03"]        # optional, dates this slot is not held
  attending = true             # set false for a slot you skip because of a clash

  [[courses.exams]]
  date = "2026-11-10"
  title = "Midterm"
  start = "18:00"              # optional

  [[courses.topics]]           # optional weekly topics from the syllabus
  week_of = "2026-10-05"       # a date in that week, usually the Monday
  title = "Sorting"
```

How recordings and photos are matched: the class that overlaps the recording most wins. Each class is widened by 15 minutes on both sides, and slots with `attending = false` are ignored.
