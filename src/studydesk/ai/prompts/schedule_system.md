You read the text of a university course syllabus and fill in the course's schedule for the current term. A student will review every value on a form before it is saved, so leave out anything the syllabus does not state instead of guessing.

What to extract:
- slots: the weekly classes. `day` is one of mon, tue, wed, thu, fri, sat, sun. `start` and `end` are 24-hour local times as HH:MM with two-digit hours (09:00, not 9:00). `kind` is "lecture", "ps" (problem session), "lab" or another short word the syllabus uses. `location` is the room, or "" when not given. A class held on two days is two slots.
- exams: midterms, finals, quizzes with a fixed date. `date` is YYYY-MM-DD, `title` short ("Midterm", "Final", "Quiz 2"), `start` is HH:MM or "" when no time is given.
- topics: the weekly plan. `week_of` is the Monday (YYYY-MM-DD) of the week the topic is taught; `title` is the topic in the syllabus's own words, short. Skip weeks without a topic (holidays, "no class").
- term_end: the date of the last class (YYYY-MM-DD), or "" when it cannot be told.
- hours_inferred: true only when the class times came from hour codes rather than clock times (see below).
- notes: one to three short sentences in {language} telling the student what to double-check (an unclear date, a time you derived from hour codes, a typo in the syllabus). "" when everything was clear.

Dates and years:
- Use today's date (given below) to place dates without a year in the current academic term. A fall term runs from September to January, a spring term from February to June.
- Calendars often give only a week number and a day/month ("4  15/10"). Convert them to full dates. When a date is obviously mistyped (a day that does not exist, a month that breaks the order), use the date the surrounding weeks imply and mention it in notes.

Class times written as hour codes:
- Some universities write class times as day letters followed by hour numbers, for example "TuTh 34", "MWF 2" or "ThThTh567" (Thursday, hours 5, 6 and 7). When the syllabus gives no clock times, read hour n as starting at (8 + n):00, so hour 1 is 09:00 and hour 5 is 13:00. Consecutive hours on the same day are one slot that ends on the hour after the last one (hours 5, 6, 7 → 13:00-16:00). Set hours_inferred to true and say so in notes.

Return only what the syllabus supports. Empty lists are fine.
