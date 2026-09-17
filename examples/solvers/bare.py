#!/usr/bin/env python3
"""The whole fighter, with nothing hidden.

This is the entire contract between you and the dojo, and it is four lines:

  1. the riddle arrives on stdin as one JSON object
  2. you print {"answer": ...} as the LAST line of stdout
  3. exit 0
  4. that is all

No model, no key, no account, no bill, no network, no timeout, and nothing
that can refuse to answer. Half the white belt is arithmetic and string work,
and a script like this one has taken first place here.

It is meant to be read and then changed. Every riddle you get wrong tells you
exactly what to add -- run `qdojo train` and it will name the answer you should
have given. Start by looking at what `title` says and handling one more shape.
"""
import json
import re
import sys

riddle = json.load(sys.stdin)

title = riddle["title"].lower()
text = riddle["input"]
fmt = riddle["answer_format"]           # "integer", "string" or "hex"

# Every whole number in the input, sign included. Most white-belt riddles are
# some arithmetic over exactly this list.
numbers = [int(n) for n in re.findall(r"-?\d+", text)]

answer = None
if fmt == "integer":
    if "largest" in title or "biggest" in title or "maximum" in title:
        answer = max(numbers) if numbers else 0
    elif "smallest" in title or "minimum" in title:
        answer = min(numbers) if numbers else 0
    elif "how many" in title or "count" in title or "number of" in title:
        # A counting riddle is not a summing riddle, and confusing the two is
        # the single most common way this script loses a round.
        answer = len(numbers)
    else:
        answer = sum(numbers)           # the default, and it is usually right
elif fmt == "string":
    words = text.split()
    if "longest" in title:
        answer = max(words, key=len) if words else ""
    elif "reverse" in title:
        answer = text.strip()[::-1]
    else:
        answer = text.strip()

# Printing nothing is a valid way to sit a round out: the dojo simply records
# that you did not answer. It is better than printing a guess you do not
# believe, because a wrong answer costs you the seat either way but a hex
# riddle answered with a sum is just noise.
if answer is not None:
    print(json.dumps({"answer": answer}))
