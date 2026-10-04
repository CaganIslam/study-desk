"""A synthetic schedule. Never use a real one in tests (ADR 0003)."""

COURSES_TOML = """
timezone = "Europe/Istanbul"
term_end = "2026-12-11"

[[closures]]
date = "2026-10-29"

[[closures]]
date = "2026-10-28"
start = "13:00"

[[courses]]
code = "CS 101"
name = "Algorithms"
folder = "CS101 Algorithms"
aliases = ["101", "algo"]
syllabus = "slides/syllabus.pdf"

  [[courses.slots]]
  day = "tue"
  start = "09:00"
  end = "11:00"
  first = "2026-09-29"
  skip = ["2026-11-03"]

  [[courses.slots]]
  day = "wed"
  start = "13:00"
  end = "15:00"

  [[courses.exams]]
  date = "2026-11-10"
  title = "Midterm"
  start = "18:00"

  [[courses.topics]]
  week_of = "2026-10-05"
  title = "Sorting"

[[courses]]
code = "CS 202"
name = "Systems"
folder = "CS202 Systems"

  [[courses.slots]]
  day = "tue"
  start = "11:00"
  end = "12:00"

  [[courses.slots]]
  day = "thu"
  start = "13:00"
  end = "16:00"

[[courses]]
code = "IE 303"
name = "Optimisation"
folder = "IE303 Optimisation"

  [[courses.slots]]
  day = "thu"
  start = "13:00"
  end = "15:00"
  attending = false

  [[courses.slots]]
  day = "fri"
  start = "14:00"
  end = "15:00"
"""
