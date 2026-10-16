#!/bin/bash
# Usage: anon_scan.sh <paper-folder>
# Lists lines that may break double-blind review. Every hit needs a human look; not all are violations.
p="${1:?paper folder}"
scan(){ local label="$1" re="$2"; local h; h=$(grep -rnEi "$re" "$p/paper" --include='*.tex' --include='*.bib' 2>/dev/null || true)
  echo "## $label"; [ -n "$h" ] && echo "$h" || echo "(none)"; }
scan "author / affiliation"      '\\(author|affiliation|institute|email|thanks)\{'
scan "acknowledgments / funding" 'acknowledg|funded by|grant (no|number)|supported by'
scan "identifying URLs"          'github\.com|gitlab\.com|huggingface\.co/[a-z]|drive\.google|dropbox|/~[a-z]'
scan "first-person prior work"   '(our|my) (prior|previous|earlier) (work|paper)|we (previously|earlier) (showed|proposed|introduced)|in our (prior|previous)'
scan "non-anonymous option"      '\\usepackage\[[^]]*(final|preprint|camera)[^]]*\]'
