# API Endpoints Reference

This document documents the API endpoints, authentication boundaries, and payloads.

## Authentication Routes (`/api/v1/auth`)

### 1. User Login
Authenticates credentials and establishes a session in Redis.

*   **URL:** `/api/v1/auth/login`
*   **Method:** `POST`
*   **Request Format:** `application/x-www-form-urlencoded`
    *   `username`: string (email)
    *   `password`: string
*   **Response (200 OK):**
    ```json
    {
      "access_token": "eyJhbGciOi...",
      "token_type": "bearer"
    }
    ```

### 2. User Logout
Invalidates the current session token in Redis.

*   **URL:** `/api/v1/auth/logout`
*   **Method:** `POST`
*   **Security:** Bearer token required
*   **Response (200 OK):**
    ```json
    {
      "detail": "Successfully logged out."
    }
    ```

### 3. Invite User
Sends an invitation to register a user. Restricted to the **ADMIN** role.

*   **URL:** `/api/v1/auth/invite`
*   **Method:** `POST`
*   **Security:** Bearer token required (Admin role only)
*   **Request Body (JSON):**
    ```json
    {
      "email": "agent@example.com",
      "roles": ["AGENT", "CONTROL"]
    }
    ```
*   **Response (200 OK):**
    ```json
    {
      "id": "716dd297-f442-4323-88c9-6c26d3b81a09",
      "email": "agent@example.com",
      "roles": ["AGENT", "CONTROL"],
      "expires_at": "2026-06-09T13:36:07.838771"
    }
    ```

### 4. Register From Invitation
Consumes an invitation token to create an active account.

*   **URL:** `/api/v1/auth/register-invite`
*   **Method:** `POST`
*   **Request Format:** `multipart/form-data`
    *   `token`: string (required invitation token)
    *   `password`: string (required new password)
    *   `profile_image`: File (optional image upload)
*   **Response (200 OK):**
    ```json
    {
      "id": "c626d3b8-4323-4423-88c9-716dd2971a09",
      "email": "agent@example.com",
      "roles": ["AGENT"],
      "is_active": true,
      "profile_image": "http://localhost:4566/app-assets/assets/abc.png"
    }
    ```

---

## User Routes (`/api/v1/users`)

### 1. Fetch Profile Info
*   **URL:** `/api/v1/users/me`
*   **Method:** `GET`
*   **Security:** Bearer token required
*   **Response (200 OK):**
    ```json
    {
      "id": "716dd297-...",
      "email": "admin@example.com",
      "roles": ["ADMIN"],
      "is_active": true,
      "profile_image": null
    }
    ```

### 2. Update Profile Image
*   **URL:** `/api/v1/users/me/profile-image`
*   **Method:** `POST`
*   **Security:** Bearer token required
*   **Request Format:** `multipart/form-data`
    *   `profile_image`: File (image file)
*   **Response (200 OK):** Returns updated user profile schema.

### 3. Generate Scoped API Key
*   **URL:** `/api/v1/users/api-keys`
*   **Method:** `POST`
*   **Security:** Bearer token required
*   **Request Body (JSON):**
    ```json
    {
      "name": "Service Key",
      "scopes": ["assets:audit"],
      "expires_in_days": 30
    }
    ```
*   **Response (201 Created):**
    ```json
    {
      "id": "f81d4fae-...",
      "name": "Service Key",
      "prefix": "ak_12345",
      "scopes": ["assets:audit"],
      "is_active": true,
      "expires_at": "2026-07-02T13:36:07.838771",
      "raw_key": "ak_1234567890abcdef1234567890ab..."
    }
    ```
    *Note: `raw_key` is shown only once upon creation.*

---

## Asset Routes (`/api/v1/assets`)

### 1. Upload Asset
*   **URL:** `/api/v1/assets/upload`
*   **Method:** `POST`
*   **Security:** Bearer token required
*   **Request Format:** `multipart/form-data`
    *   `file`: File (arbitrary format)
*   **Response (201 Created):**
    ```json
    {
      "filename": "document.pdf",
      "url": "http://localhost:4566/app-assets/assets/xyz.pdf"
    }
    ```

### 2. Get Secure Configuration
*   **URL:** `/api/v1/assets/secure-config`
*   **Method:** `GET`
*   **Security:** Client IP must be whitelisted
*   **Response (200 OK):**
    ```json
    {
      "status": "authorized",
      "message": "You are accessing this endpoint from a whitelisted IP address.",
      "whitelisted_ip_checked": "Passed"
    }
    ```

### 3. Get Audit Log
*   **URL:** `/api/v1/assets/audit`
*   **Method:** `GET`
*   **Security:** Header `X-API-Key` with scope `assets:audit`
*   **Response (200 OK):**
    ```json
    {
      "status": "authorized",
      "api_key_name": "Service Key",
      "allowed_scopes": ["assets:audit"],
      "message": "Scope verification successful. Access granted to audit logs."
    }
    ```
