# **Explanation of `/operator_status`, `/mesin/status`, and `/operator/status`**

### **Explanation of Mesin Status and Displayed Status**

#### **Definitions**
- **Mesin Status**:
  - Determines which front-end page should be displayed.
  - Indicates if reject and rework input is required.
  - Can be one of the following:
    - **RUNNING**: Operator is actively running the machine.
    - **IDLE**: Machine is not in use, and no production is ongoing.
    - **SETUP**: Machine setup is in progress, and reject/rework inputs are enabled.

- **Displayed Status**:
  - Represents the current activity of the operator.
  - Tracks whether the operator is engaged with the machine.
  - Used for reporting purposes and guiding user options.
  - Can be one of the following:
    - **RUNNING**: Operator is actively running the machine.
    - **IDLE**: Operator is not working on the machine.
    - **DOWNTIME**: Operator is engaged in a downtime activity related to the machine.

---

### **Status Mapping Table**

| **Code** | **Category**         | **Mesin Status**     | **Displayed Status**  |
|----------|---------------------|---------------------|-----------------------|
| **BR**   | Briefing             | **IDLE**            | **IDLE**               |
| **BT**   | Breaktime            | **IDLE**            | **IDLE**               |
| **NP**   | No Plan              | **IDLE**            | **IDLE**               |
| **TL**   | Trial                | **SETUP**           | **DOWNTIME**           |
| **TS**   | Tooling Setting      | **SETUP**           | **DOWNTIME**           |
| **TP**   | Tooling Problem      | **SETUP**           | **DOWNTIME**           |
| **MP**   | Machine Problem      | **IDLE**            | **DOWNTIME**           |
| **CM**   | Change Material      | **IDLE**            | **DOWNTIME**           |
| **QC**   | Quality Check        | **IDLE**            | **DOWNTIME**           |
| **NM**   | No Material          | **IDLE**            | **DOWNTIME**           |
| **RP**   | Reporting            | **IDLE**            | **DOWNTIME**           |
| **STO**  | Stock Opname         | **IDLE**            | **DOWNTIME**           |
| **X**    | Lain - lain (Others) | **IDLE**            | **DOWNTIME**           |
| **RUNNING**| Running            | **RUNNING**         | **RUNNING**            |

---

### **Mapping Rules**

#### **Mesin Status**
- If the **category** is one of **TL, TS, TP**, then **Mesin Status** = **SETUP**
- Otherwise, **Mesin Status** = **IDLE**

#### **Displayed Status**
- If the **category** is one of **BR, BT, NP**, then **Displayed Status** = **IDLE**
- Otherwise, **Displayed Status** = **DOWNTIME**

---

### **Key Takeaways**
- **Mesin Status** tells the system which page to navigate to and if reject/rework should be enabled.
- **Displayed Status** is used for reporting purposes and operator state tracking.
- **Mesin Status** can be **RUNNING**, **IDLE**, or **SETUP**.
- **Displayed Status** can be **RUNNING**, **IDLE**, or **DOWNTIME**.
- **Categories** drive the statuses, and specific categories like **TL, TS, TP** trigger **SETUP** for **Mesin Status**.



Mesin status (running, idle, setup) is for determining which page we should go in frontend. If running, then stop. if idle or setup, then start. Also, if setup, then we give user ability to insert reject and rework.
Displayed status (running, idle, downtime) is for determining what the operator is currently doing. If idle, then operator is not running, mulai aktivitas baru. If running/downtime, then the operator is "running". If running, then option is stop running. If downtime, then option is "stop kategori downtime".

This document explains the purpose and functionality of the following API endpoints:
- **/operator_status**
- **/mesin/status**
- **/operator/status**

The focus is on how these endpoints control the interaction between **operators**, **machines**, and the **status of activities**. Each endpoint plays a crucial role in ensuring only one operator can run a machine at a time, determining how operators interact with the system, and controlling the UI/UX flow of the application.

---

## **1. Summary of Key Concepts**

| **Endpoint**         | **Purpose**                                      | **Used In**          | **What It Checks/Returns**                          | **Action it Triggers in Frontend**         |
|---------------------|-------------------------------------------------|---------------------|---------------------------------------------------|--------------------------------------------|
| **`/operator_status`**| Ensures the operator is allowed to operate a machine | **ConfirmScreen**    | Ensures machine is **not running** or is run by the request's operator | If not allowed, block access. If allowed, allow to continue. |
| **`/mesin/status`**   | Returns the machine's current operational status  | **ConfirmScreen**    | **Status of the machine** (`RUNNING`, `IDLE`, `SETUP`) | If **RUNNING**, go to **StopScreen**. If **IDLE** or **SETUP**, go to **StartScreen**. |
| **`/operator/status`**| Returns details of the current operator's state  | **MainScreen**       | Whether the operator is **running or not**, and the **displayed_status** (`RUNNING`, `IDLE`, `DOWNTIME`) | If operator is **running**, go to **ConfirmScreen**. If not running, allow new activity. |

---

## **2. Detailed Explanation of Each Endpoint**

### **1. /operator_status**

**Purpose**:
This endpoint ensures that only **one operator can operate one machine at a time**, and **only the operator who started the activity can stop it**.

**What it does**:
1. It checks the **machine status** (`mesin_status`).
   - If the machine is already **RUNNING** and it is being run by **another operator**, it blocks the action.
   - If the machine is **RUNNING**, but it is being run by the **current operator**, then it allows access.
   - If the machine is **IDLE**, it allows the operator to start a new activity.

**Backend Code (business_logic.py)**
```python
    def check_operator_status(request, session):
        mesin_status_ok, mesin_error_msg = check_mesin(
            mesin_id=request.mesin_id,
            operator_id=request.operator_id,
            session=session
        )

        operator_status_ok = False
        operator_error_msg = ""
        if mesin_status_ok:
            operator_status_ok, operator_error_msg = check_operator(
                tooling_id=request.tooling_id,
                mesin_id=request.mesin_id,
                operator_id=request.operator_id,
                session=session,
            )

        return {
            "isSuccess": operator_status_ok and mesin_status_ok,
            "errorMessage": operator_error_msg + mesin_error_msg,
        }
```

**Frontend Code (ConfirmScreen.kt)**
```kotlin
API.checkOperatorStatus(
    toolingId = tooling.value ?: "",
    mesinId = mesin.value ?: "",
    operatorId = operator.value ?: "",
    ResponseListener = { response ->
        val isOk: Boolean = response.getBoolean("isSuccess")
        if (isOk) {
            // Continue the process
        } else {
            imnViewModel.updateDetails(
                detailText = response.getString("errorMessage"),
                isSuccessful = false
            )
        }
    }
)
```

---

### **2. /mesin/status**

**Purpose**:
Returns the current **operational status of the machine**. It tells the system what screen to navigate to next (StartScreen, StopScreen, etc.).

**What it does**:
1. It returns **RUNNING, IDLE, or SETUP** for a given machine.
2. This is used to determine **what screen to show next**:
   - If **RUNNING**, go to **StopScreen**.
   - If **IDLE**, go to **StartScreen** to allow the operator to start the machine.
   - If **SETUP**, go to **StartScreen**, but with the requirement to input rework and reject quantities.

**Backend Code (FastAPI)**
```python
@app.get("/mesin/status/{mesin_id}")
def get_mesin_status(mesin_id: str, session=Sessioner):
    status = models.Status.IDLE
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is not None:
        status = mesin_status.status
    return {"status": status}
```

**Frontend Code (ConfirmScreen.kt)**
```kotlin
API.getMesinStatus(
    mesin.value ?: "NONE",
    { response -> imnViewModel.setMesinStatus(response.getString("status")) },
    { error ->
        imnViewModel.updateDetails(
            detailText = "Mesin status invalid",
            isSuccessful = false
        )
    }
)
```

---

### **3. /operator/status**

**Purpose**:
Returns detailed information about the current **operator's activity and state**. It tells the system if the operator is already running an activity and what the operator's current state is.

**What it does**:
1. It tells if the **operator is running** an activity on a machine.
2. It returns the **operator's current displayed status**:
   - If **RUNNING**, then show **Stop Running** button.
   - If **DOWNTIME**, show **Change Downtime Category** button.
   - If **IDLE**, allow the operator to start a new activity.

**Backend Code (business_logic.py)**
```python
def is_operator_running(operator_id, session):
    operator_status = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )

    if operator_status is None:
        return False, models.DisplayedStatus.IDLE, "", ""

    if operator_status.status == models.DisplayedStatus.IDLE:
        return False, operator_status.status, "", ""
    else:
        return (
            True,
            operator_status.status,
            operator_status.last_tooling_id,
            operator_status.last_mesin_id,
        )
```

**Frontend Code (MainScreen.kt)**
```kotlin
API.getOperatorStatus(
    operatorId,
    { response ->
        isCallSuccessful.value = true
        dataStore.saveSelectedTooling(response.getString("toolingId"))
        dataStore.saveSelectedMesin(response.getString("mesinId"))
        isOperatorRunning.value = response.getBoolean("isRunning")
        operatorStatus.value = response.getString("operatorStatus")
    },
    { error ->
        error.message?.let { Log.e("API", it) }
    }
)
```

---

## **4. Summary of Flow**

1. **MainScreen**: Operator logs in, calls **`/operator/status`** to determine if the operator is already running.
2. **ConfirmScreen**: Checks if the operator can access the machine with **`/operator_status`**.
3. **ConfirmScreen**: Gets the status of the machine with **`/mesin/status`** to decide the next screen.

# API Documentation

This document describes the APIs, data models, and workflows for managing machine (*mesin*) and operator activities in a manufacturing environment. It includes details on the endpoints, their purpose, and the underlying data models.

---

## **Endpoints**

### **1. `/operator/status/{operator_id}`**
- **Method**: GET
- **Purpose**: Retrieves the current status of an operator.
- **Parameters**:
  - `operator_id` (string): The unique ID of the operator.
- **Response**:
  ```json
  {
    "isRunning": true/false,
    "operatorStatus": "RUNNING/IDLE/DOWNTIME",
    "toolingId": "<tooling_id>",
    "mesinId": "<mesin_id>"
  }
  ```
- **Workflow**:
  - Checks the operator's status in the `OperatorStatus` table.
  - Returns whether the operator is running and details of the current activity.

### **2. `/operator_status_all/`**
- **Method**: GET
- **Purpose**: Retrieves the statuses of all operators.
- **Response**:
  - List of all `OperatorStatus` entries.
- **Workflow**:
  - Queries the `OperatorStatus` table and returns all records.

---

## **Data Models**

### **1. `MesinLog`**
Logs all machine-related activities, including starts, stops, and transitions.

| **Attribute**          | **Type**          | **Description**                                    |
|------------------------|-------------------|--------------------------------------------------|
| `id`                  | Integer          | Unique ID for the log entry.                     |
| `tooling_id`          | String           | ID of the tooling used in the activity.          |
| `mesin_id`            | String           | ID of the machine involved.                      |
| `operator_id`         | String           | ID of the operator performing the action.        |
| `timestamp`           | DateTime         | Time of the activity.                            |
| `output`              | Integer (nullable)| Number of items produced (if applicable).        |
| `downtime_category`   | String           | Category of downtime (default: `U : Utility`).   |
| `category`            | Enum             | Type of activity (`START` or `STOP`).            |
| `time_created`        | DateTime         | Record creation timestamp.                       |
| `time_updated`        | DateTime         | Record update timestamp.                         |

### **2. `ActivityMesin`**
Summarizes activities by linking start and stop events and capturing production details.

| **Attribute**          | **Type**          | **Description**                                    |
|------------------------|-------------------|--------------------------------------------------|
| `id`                  | Integer          | Unique ID for the activity.                      |
| `mesin_id`            | String           | ID of the machine involved.                      |
| `operator_id`         | String           | ID of the operator involved.                     |
| `start_time_id`       | Integer          | Foreign key to the start log in `MesinLog`.      |
| `stop_time_id`        | Integer          | Foreign key to the stop log in `MesinLog`.       |
| `output`              | Integer          | Number of items produced during the activity.    |
| `reject`              | Integer          | Number of rejected items.                        |
| `rework`              | Integer          | Number of items requiring rework.                |
| `coil_no`, `lot_no`, `pack_no` | String | Additional identifiers.                          |
| `downtime_category`   | String           | Category of downtime.                            |
| `time_created`        | DateTime         | Record creation timestamp.                       |
| `time_updated`        | DateTime         | Record update timestamp.                         |

### **3. `MesinStatus`**
Tracks the current state of a machine, including its last activity and associated operator/tooling.

| **Attribute**          | **Type**          | **Description**                                    |
|------------------------|-------------------|--------------------------------------------------|
| `id`                  | String           | Unique ID of the machine.                        |
| `status`              | Enum             | Current machine state (`RUNNING`, `IDLE`).       |
| `last_start_id`       | Integer          | Foreign key to the last start log.               |
| `last_stop_id`        | Integer          | Foreign key to the last stop log.                |
| `last_tooling_id`     | String           | Tooling used in the last activity.               |
| `last_operator_id`    | String           | Operator involved in the last activity.          |
| `category_downtime`   | String           | Last downtime category.                          |
| `displayed_status`    | Enum             | Displayed status (`RUNNING`, `IDLE`).            |
| `time_created`        | DateTime         | Record creation timestamp.                       |
| `time_updated`        | DateTime         | Record update timestamp.                         |

### **4. `OperatorStatus`**
Tracks the current status of an operator.

| **Attribute**          | **Type**          | **Description**                                    |
|------------------------|-------------------|--------------------------------------------------|
| `id`                  | String           | Unique ID of the operator.                       |
| `status`              | Enum             | Current operator state (`RUNNING`, `IDLE`).      |
| `last_tooling_id`     | String           | Tooling used in the last activity.               |
| `last_mesin_id`       | String           | Machine used in the last activity.               |
| `time_created`        | DateTime         | Record creation timestamp.                       |
| `time_updated`        | DateTime         | Record update timestamp.                         |

---

## **Workflows**

### **Starting an Activity**
1. **API Endpoint**: Not exposed; internally invoked.
2. **Steps**:
   - Validate operator and machine statuses.
   - Create a `MesinLog` entry for the `START` event.
   - Update `MesinStatus` and `OperatorStatus` to reflect the new activity.

### **Stopping an Activity**
1. **API Endpoint**: Not exposed; internally invoked.
2. **Steps**:
   - Validate the current machine state.
   - Create a `MesinLog` entry for the `STOP` event.
   - Generate an `ActivityMesin` record linking the start and stop logs.
   - Update `MesinStatus` and `OperatorStatus` accordingly.

### **Checking Status**
- **Endpoints**:
  - `/operator/status/{operator_id}`
  - `/operator_status_all/`
- **Steps**:
  - Query the relevant status tables (`OperatorStatus`, `MesinStatus`).
  - Return the current state along with any associated tooling or machine IDs.

---

## **Frontend Interaction**

| **Endpoint**         | **Purpose**                                      | **Frontend Usage**         | **Actions**                                      |
|----------------------|-------------------------------------------------|---------------------------|------------------------------------------------|
| `/operator/status`   | Fetches operator status.                        | **MainScreen**            | Checks if operator is running.                 |
| `/operator_status_all`| Retrieves all operator statuses.                | **AdminDashboard**        | Displays an overview of all operators.         |

---

## **Error Handling**
- **Invalid State Transitions**:
  - If an operator attempts to start an already running machine, an `HTTP 403` is raised.
  - If a stop operation is issued for an idle machine, an `HTTP 403` is raised.
- **Data Integrity**:
  - Ensures all logs and statuses are synchronized.
  - Transactions are committed only if all validations pass.

---

This API documentation provides a complete overview of the functionality, enabling seamless integration and operational efficiency.


