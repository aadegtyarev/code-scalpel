# Review configuration

review-diff-model: auto
review-full-model: auto
audit-model: auto
review-scope: auto

<!--
Each model setting = auto | session | <model id e.g. opus / sonnet>. Absent/unrecognized ⇒ auto.
- auto: review/audit run on a DIFFERENT model than the session (independent blind spots); reviewer model is named at launch.
- session: review runs on the session model (opt out of cross-model).
- <model id>: pin a specific reviewer. (Haiku is blacklisted for review.)
Plan and code always run on the session model. Set at bootstrap; change by editing this file or asking Claude.
-->
