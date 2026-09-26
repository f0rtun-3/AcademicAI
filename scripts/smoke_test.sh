#!/bin/bash
# Real HTTP smoke test against a running Flask server.
set -u
B=http://127.0.0.1:5000
DB=${ACADEMICAI_DB_PATH:?ACADEMICAI_DB_PATH must be set to the running server database}
pass=0; fail=0
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "  PASS  $1 ($3)"; pass=$((pass+1));
  else echo "  FAIL  $1 (expected $2, got $3)"; fail=$((fail+1)); fi
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

echo "1. Unauthenticated"
check "GET /api/health" 200 "$(code $B/api/health)"
check "GET /api/dashboard without token" 401 "$(code $B/api/dashboard)"
check "GET /api/events without token" 401 "$(code $B/api/events)"
check "GET /api/auth/me with garbage token" 401 "$(code -H 'Authorization: Bearer nonsense' $B/api/auth/me)"

echo "2. Registration"
REG=$(curl -s -X POST $B/api/auth/register -H 'Content-Type: application/json' -d '{
 "full_name":"Smoke Student","email":"smoke1@student.babcock.edu.ng","password":"Password123",
 "confirm_password":"Password123","university":"Babcock University",
 "department":"Software Engineering","level":"200","academic_session":"2026/2027",
 "student_id_number":"BU/SEN/0001"}')
check "POST /api/auth/register" "Smoke Student" "$(echo "$REG" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["full_name"])')"
check "verification token withheld in production mode" "absent" \
  "$(echo "$REG" | python3 -c 'import sys,json;print("present" if "verification_token" in json.load(sys.stdin) else "absent")')"
check "duplicate registration rejected" 409 "$(code -X POST $B/api/auth/register -H 'Content-Type: application/json' -d '{
 "full_name":"Smoke Student","email":"smoke1@student.babcock.edu.ng","password":"Password123",
 "confirm_password":"Password123","university":"Babcock University",
 "department":"Software Engineering","level":"200","academic_session":"2026/2027",
 "student_id_number":"BU/SEN/0001"}')"
check "registration without a student ID rejected" 400 "$(code -X POST $B/api/auth/register -H 'Content-Type: application/json' -d '{
 "full_name":"No Id","email":"smoke2@student.babcock.edu.ng","password":"Password123",
 "confirm_password":"Password123","university":"Babcock University",
 "department":"Software Engineering","level":"200","academic_session":"2026/2027"}')"

echo "2b. Institutional email domain (Gate 1)"
# The probe matrix below makes more registration attempts than the per-IP
# limit allows, so this script runs the server with rate limiting off. The
# limiter itself is covered by test_institutional_email.py.
check "GET /api/universities" 200 "$(code $B/api/universities)"
check "registry lists exactly the four supported universities" 4 "$(curl -s $B/api/universities | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["universities"]))')"
check "registry is read-only" 405 "$(code -X POST $B/api/universities)"

reg_domain() { # university email -> status code
  code -X POST $B/api/auth/register -H 'Content-Type: application/json' -d "{
   \"full_name\":\"Domain Probe\",\"email\":\"$2\",\"password\":\"Password123\",
   \"confirm_password\":\"Password123\",\"university\":\"$1\",
   \"department\":\"Software Engineering\",\"level\":\"200\",
   \"academic_session\":\"2026/2027\",\"student_id_number\":\"BU/SEN/0002\"}"
}

check "Babcock + gmail rejected" 400 "$(reg_domain 'Babcock University' 'p1@gmail.com')"
check "Babcock + Covenant domain rejected" 400 "$(reg_domain 'Babcock University' 'p2@stu.cu.edu.ng')"
check "Covenant + Babcock domain rejected" 400 "$(reg_domain 'Covenant University' 'p3@student.babcock.edu.ng')"
check "Ibadan + UNILAG domain rejected" 400 "$(reg_domain 'University of Ibadan' 'p4@unilag.edu.ng')"
check "bare babcock.edu.ng rejected (no generic .edu.ng rule)" 400 "$(reg_domain 'Babcock University' 'p5@babcock.edu.ng')"
check "lookalike domain rejected" 400 "$(reg_domain 'Babcock University' 'p6@student.babcock.edu.ng.attacker.com')"
check "unsupported university rejected" 400 "$(reg_domain 'Obafemi Awolowo University' 'p7@oauife.edu.ng')"
check "UNILAG + unilag.edu.ng accepted" 201 "$(reg_domain 'University of Lagos' 'p8@unilag.edu.ng')"
check "Ibadan + stu.ui.edu.ng accepted" 201 "$(reg_domain 'University of Ibadan' 'p9@stu.ui.edu.ng')"
check "Covenant + stu.cu.edu.ng accepted" 201 "$(reg_domain 'Covenant University' 'p10@stu.cu.edu.ng')"
check "uppercase institutional domain accepted" 201 "$(reg_domain 'Babcock University' 'P11@STUDENT.BABCOCK.EDU.NG')"

REJECTED_USERS=$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
bad = ("p1@gmail.com", "p2@stu.cu.edu.ng", "p3@student.babcock.edu.ng",
       "p4@unilag.edu.ng", "p5@babcock.edu.ng",
       "p6@student.babcock.edu.ng.attacker.com", "p7@oauife.edu.ng")
rows = conn.execute(
    "SELECT COUNT(*) FROM users WHERE email IN (%s)" % ",".join("?" * len(bad)), bad
).fetchone()[0]
ghosts = conn.execute(
    "SELECT COUNT(*) FROM universities WHERE name = 'Obafemi Awolowo University'"
).fetchone()[0]
print(rows + ghosts)
PY
)
check "no account or university created by a rejected attempt" 0 "$REJECTED_USERS"

echo "3. Authenticated route"
TOKEN=$(curl -s -X POST $B/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"smoke1@student.babcock.edu.ng","password":"Password123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
check "login returns a token" "yes" "$([ -n "$TOKEN" ] && echo yes || echo no)"
ME=$(curl -s -H "Authorization: Bearer $TOKEN" $B/api/auth/me)
check "GET /api/auth/me authenticated" 200 "$(code -H "Authorization: Bearer $TOKEN" $B/api/auth/me)"
check "next_step drives onboarding" "verify_email" "$(echo "$ME" | python3 -c 'import sys,json;print(json.load(sys.stdin)["next_step"])')"

echo "4. Authorization failures (authenticated but not entitled)"
check "the removed identity endpoint is gone" 404 "$(code -X POST $B/api/auth/identity -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}')"
check "community setup before email verification" 403 "$(code -X POST $B/api/community/setup -H "Authorization: Bearer $TOKEN")"
check "dashboard without membership" 403 "$(code -H "Authorization: Bearer $TOKEN" $B/api/dashboard)"
check "publish without rep authority" 403 "$(code -X POST $B/api/ai/publish -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"action":"CREATE","scope":"EVENT","title":"x","event_type":"QUIZ"}')"

echo "5. Email verification is the account gate"
# Confirm the email out of band, standing in for the emailed link.
python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("UPDATE users SET email_verified = 1 WHERE email='smoke1@student.babcock.edu.ng'")
conn.commit()
PY
EMAIL_OK=$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    "SELECT email_verified FROM users WHERE email='smoke1@student.babcock.edu.ng'").fetchone()
print(row[0] if row else "missing")
PY
)
check "email marked verified" "1" "$EMAIL_OK"

ME2=$(curl -s -H "Authorization: Bearer $TOKEN" $B/api/auth/me)
check "onboarding goes straight to community setup" "community_setup" \
  "$(echo "$ME2" | python3 -c 'import sys,json;print(json.load(sys.stdin)["next_step"])')"
check "no identity status is reported" "absent" \
  "$(echo "$ME2" | python3 -c 'import sys,json;print("present" if "identity_status" in json.load(sys.stdin)["user"] else "absent")')"
check "no identity_check block is reported" "absent" \
  "$(echo "$ME2" | python3 -c 'import sys,json;print("present" if "identity_check" in json.load(sys.stdin) else "absent")')"

# Nobody is silently stamped VERIFIED by the removal of the ID-card check.
STAMPED=$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
print(conn.execute(
    "SELECT identity_status FROM users WHERE email='smoke1@student.babcock.edu.ng'"
).fetchone()[0])
PY
)
check "legacy identity column left at its default" "UNVERIFIED" "$STAMPED"
NEWROWS=$(python3 - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
print(conn.execute("SELECT COUNT(*) FROM identity_verifications").fetchone()[0])
PY
)
check "nothing is written to the legacy identity table" 0 "$NEWROWS"

echo "6. Authorization follows membership, not the account gate"
check "verified email still has no membership" 403 "$(code -H "Authorization: Bearer $TOKEN" $B/api/dashboard)"
check "verified email may now reach community setup" 201 "$(code -X POST $B/api/community/setup -H "Authorization: Bearer $TOKEN")"
check "verified email still cannot publish" 403 "$(code -X POST $B/api/ai/publish -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"action":"CREATE","scope":"EVENT","title":"x","event_type":"QUIZ"}')"

echo "6b. Read-only election visibility (J4)"
# Membership is required to read the community, so join first. The community
# has no rep yet, so this becomes an ACTIVE membership immediately.
check "an email-verified student may join the community it just created" 201 \
  "$(code -X POST $B/api/community/join -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}')"
# cooldown_until and the threshold numbers are UI hints. They must be present
# for the viewer, must never authorize anything, and must never report another
# student's cooldown.
COMMUNITY_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" $B/api/community)
check "GET /api/community carries the election object" "yes" \
  "$(echo "$COMMUNITY_JSON" | python3 -c 'import sys,json;print("yes" if "election" in json.load(sys.stdin)["community"] else "no")')"
check "election reports required_members from config, not a client constant" "4" \
  "$(echo "$COMMUNITY_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["community"]["election"]["required_members"])')"
check "cooldown_until present for the viewer" "yes" \
  "$(echo "$COMMUNITY_JSON" | python3 -c 'import sys,json;print("yes" if "cooldown_until" in json.load(sys.stdin)["community"]["election"] else "no")')"
check "no cooldown for a student who has not stood" "None" \
  "$(echo "$COMMUNITY_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["community"]["election"]["cooldown_until"])')"
check "no max_reps is invented in the payload" "absent" \
  "$(echo "$COMMUNITY_JSON" | python3 -c 'import sys,json;print("present" if "max_reps" in json.load(sys.stdin)["community"]["election"] else "absent")')"

echo "6c. Authenticated email change (J3)"
check "change-email requires authentication" 401 \
  "$(code -X POST $B/api/auth/change-email -H 'Content-Type: application/json' -d '{"email":"x@student.babcock.edu.ng"}')"
check "change-email re-runs the domain check" 400 \
  "$(code -X POST $B/api/auth/change-email -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"email":"smoke@gmail.com"}')"
check "email unchanged after a refused change" "smoke1@student.babcock.edu.ng" \
  "$(curl -s -H "Authorization: Bearer $TOKEN" $B/api/auth/me | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["email"])')"
CHANGED=$(curl -s -X POST $B/api/auth/change-email -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"email":"smoke1moved@student.babcock.edu.ng"}')
check "change-email accepted for an approved domain" "smoke1moved@student.babcock.edu.ng" \
  "$(echo "$CHANGED" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["email"])')"
check "verification cleared by the change" "False" \
  "$(echo "$CHANGED" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["email_verified"])')"
check "the calling session is revoked by its own request" 401 \
  "$(code -H "Authorization: Bearer $TOKEN" $B/api/auth/me)"
check "no verification token leaked outside testing" "absent" \
  "$(echo "$CHANGED" | python3 -c 'import sys,json;print("present" if "verification_token" in json.load(sys.stdin) else "absent")')"

echo "7. Configuration must not silently downgrade"
check "no heuristic identity provider remains" 0 "$(grep -rl HeuristicIdentityProvider backend/academicai 2>/dev/null | wc -l | tr -d ' ')"
# MVP SCOPE: student ID-card verification is removed. A dead provider left on
# disk is a switch waiting to be flipped, so assert the files are really gone.
check "no identity vision module remains" 0 "$(ls backend/academicai/ai/identity_vision.py 2>/dev/null | wc -l | tr -d ' ')"
check "no local OCR module remains" 0 "$(ls backend/academicai/ai/local_ocr.py 2>/dev/null | wc -l | tr -d ' ')"
check "no identity service remains" 0 "$(ls backend/academicai/services/identity_service.py 2>/dev/null | wc -l | tr -d ' ')"
check "no OCR dependency file remains" 0 "$(ls backend/requirements-ocr.txt 2>/dev/null | wc -l | tr -d ' ')"
# config.py intentionally NAMES the removed variables to say they are absent,
# so check for real code usage rather than for the word appearing anywhere.
check "no pytesseract usage remains" 0 "$(grep -rl 'pytesseract' backend/academicai 2>/dev/null | wc -l | tr -d ' ')"
check "no identity upload route remains" 0 "$(grep -c 'auth/identity' backend/academicai/api/auth_routes.py | tr -d ' ')"
# Stale bytecode for a deleted module is clutter that also defeats greps.
check "no stale bytecode for removed modules" 0 \
  "$(ls backend/academicai/*/__pycache__/{identity_vision,local_ocr,ocr_text,identity_service,identity_matching,temp_storage,image_validation}.*.pyc 2>/dev/null | wc -l | tr -d ' ')"

echo "8. Error shape"
check "unknown route returns JSON 404" 404 "$(code $B/api/nope)"
check "wrong method returns 405" 405 "$(code $B/api/auth/login)"
check "404 body is JSON" "not_found" "$(curl -s $B/api/nope | python3 -c 'import sys,json;print(json.load(sys.stdin)["error"])')"
check "logout revokes the session" 401 "$(curl -s -o /dev/null -X POST $B/api/auth/logout -H "Authorization: Bearer $TOKEN" && code -H "Authorization: Bearer $TOKEN" $B/api/auth/me)"

echo
echo "SMOKE RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
