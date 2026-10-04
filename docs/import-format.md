# Importing study history

`study-desk import-sessions history.json` adds study sessions from another tool (for example notes taken while studying with Claude Code in a terminal). Each session becomes slide views at its date, so resume points, sessions and course statistics reflect it; its questions are kept with the course and its terms go into the glossary. Importing the same file again changes nothing.

```json
{
  "sessions": [
    {
      "course": "CS 101",
      "date": "2026-09-22",
      "time": "09:16-10:48",
      "deck": "Lec01-intro.pdf",
      "slides_covered": [1, 2, 14, 15, 16],
      "last_slide": 16,
      "questions": ["what is a ground truth label?"],
      "terms": [{"en": "ground truth labels", "asked": true}, {"en": "L2 norm", "asked": true}],
      "known": ["L2 norm"]
    },
    {
      "course": "CS 101",
      "date": "2026-09-23",
      "slides_covered": {"Lec01-intro.pdf": [26, 27], "Lec02-Perceptron.pdf": [1, 2, 3, 4]},
      "last_slide": {"Lec01-intro.pdf": 33, "Lec02-Perceptron.pdf": 4}
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `course` | A course code from `courses.toml`. Sessions of unknown courses are skipped with a warning. |
| `date`, `time` | Local date, and optionally `HH:MM-HH:MM`. Without a time, 09:00 is used. |
| `deck` + `slides_covered` | The deck file name in the course's `slides/` folder and the slide numbers the lecturer uses. For several decks, make `slides_covered` (and `last_slide`) a map from file name to numbers. Decks that are not there are skipped with a warning. |
| `last_slide` | Where the session ended; it becomes the resume point if it is the latest. |
| `questions` | Questions asked in that session. Answers are not imported. |
| `terms` | Terms that came up. `asked: true` marks them as hard. |
| `known` | Terms the student said they already knew; they are marked known. |

Other fields are ignored.
