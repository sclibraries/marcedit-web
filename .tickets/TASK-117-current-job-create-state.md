Title: Fix create-job current job Streamlit state error

Scope:
- Fix the Home page create-job flow that mutates `current_job_id` after the
  Streamlit widget with the same key has been instantiated.
- Add a regression test for the create-job state transition.

Success Criteria:
- Creating a job no longer raises `StreamlitAPIException` for
  `st.session_state.current_job_id`.
- The newly created job is selected after the rerun.
- Relevant tests fail before the fix and pass after the fix.

Status: Completed
