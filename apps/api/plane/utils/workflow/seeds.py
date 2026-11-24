# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Built-in workflows (PLN-005 Bug, PLN-006 Task / Story / Epic).

``allowed_roles`` uses role keys. An empty list means any contributor. Admins can always
override a transition unless ``admin_override`` is switched off on it.
"""

ANY = []
ADM_MEM = ["admin", "member"]
QA_ADM = ["qa", "admin"]
DEV_QA_ADM = ["developer", "qa", "admin"]

# (name, group, sequence, is_initial, is_final)
# transitions: (from, to, allowed_roles)

WORKFLOW_SEEDS = {
    "bug": {
        "name": "Bug workflow",
        "states": [
            ("New", "unstarted", 15000, True, False),
            ("In Progress", "started", 25000, False, False),
            ("Code Review", "started", 35000, False, False),
            ("In Testing", "started", 45000, False, False),
            ("Tested", "started", 55000, False, False),
            ("Closed", "completed", 65000, False, True),
            ("Reopened", "unstarted", 75000, False, False),
            ("Rejected", "cancelled", 85000, False, True),
        ],
        "transitions": [
            ("New", "In Progress", ANY),
            ("New", "Rejected", ADM_MEM),
            ("In Progress", "Code Review", ANY),
            ("In Progress", "In Testing", ANY),
            ("In Progress", "Rejected", ADM_MEM),
            ("Code Review", "In Progress", ANY),
            ("Code Review", "In Testing", ANY),
            ("In Testing", "Tested", QA_ADM),
            ("In Testing", "In Progress", ANY),
            ("Tested", "Closed", QA_ADM),
            ("Tested", "Reopened", ["qa", "admin", "member"]),
            ("Tested", "In Testing", QA_ADM),
            ("Closed", "Reopened", QA_ADM),
            ("Reopened", "In Progress", ANY),
            ("Reopened", "Rejected", ADM_MEM),
        ],
    },
    "task": {
        "name": "Task workflow",
        "states": [
            ("Backlog", "backlog", 15000, True, False),
            ("Todo", "unstarted", 25000, False, False),
            ("In Progress", "started", 35000, False, False),
            ("Blocked", "started", 45000, False, False),
            ("Done", "completed", 55000, False, True),
            ("Cancelled", "cancelled", 65000, False, True),
        ],
        "transitions": [
            ("Backlog", "Todo", ANY),
            ("Backlog", "Cancelled", ADM_MEM),
            ("Todo", "In Progress", ANY),
            ("Todo", "Blocked", ANY),
            ("Todo", "Cancelled", ADM_MEM),
            ("In Progress", "Blocked", ANY),
            ("In Progress", "Done", ANY),
            ("In Progress", "Cancelled", ADM_MEM),
            ("Blocked", "In Progress", ANY),
            ("Blocked", "Cancelled", ADM_MEM),
            ("Done", "In Progress", ADM_MEM),
            ("Cancelled", "Backlog", ADM_MEM),
        ],
    },
    "story": {
        "name": "Story workflow",
        "states": [
            ("Backlog", "backlog", 15000, True, False),
            ("Ready", "unstarted", 25000, False, False),
            ("In Progress", "started", 35000, False, False),
            ("In Review", "started", 45000, False, False),
            ("Done", "completed", 55000, False, True),
            ("Cancelled", "cancelled", 65000, False, True),
        ],
        "transitions": [
            ("Backlog", "Ready", ANY),
            ("Backlog", "Cancelled", ADM_MEM),
            ("Ready", "In Progress", ANY),
            ("Ready", "Cancelled", ADM_MEM),
            ("In Progress", "In Review", ANY),
            ("In Progress", "Done", DEV_QA_ADM),
            ("In Progress", "Cancelled", ADM_MEM),
            ("In Review", "In Progress", ANY),
            ("In Review", "Done", DEV_QA_ADM),
            ("In Review", "Cancelled", ADM_MEM),
            ("Done", "In Progress", ADM_MEM),
            ("Cancelled", "Backlog", ADM_MEM),
        ],
    },
    "epic": {
        "name": "Epic workflow",
        "states": [
            ("Proposed", "backlog", 15000, True, False),
            ("Approved", "unstarted", 25000, False, False),
            ("In Progress", "started", 35000, False, False),
            ("Done", "completed", 55000, False, True),
            ("Cancelled", "cancelled", 65000, False, True),
        ],
        "transitions": [
            ("Proposed", "Approved", QA_ADM),
            ("Proposed", "Cancelled", ADM_MEM),
            ("Approved", "In Progress", ANY),
            ("Approved", "Cancelled", ADM_MEM),
            ("In Progress", "Done", QA_ADM),
            ("In Progress", "Cancelled", ADM_MEM),
            ("Done", "In Progress", ADM_MEM),
            ("Cancelled", "Proposed", ADM_MEM),
        ],
    },
}

STATE_COLORS = {
    "backlog": "#60646C",
    "unstarted": "#60646C",
    "started": "#F59E0B",
    "completed": "#16A34A",
    "cancelled": "#DC2626",
}
