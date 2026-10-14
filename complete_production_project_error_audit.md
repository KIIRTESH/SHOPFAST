# Complete Production-Level Project Error Audit Prompt

You are a team of **15+ years experienced senior software engineers, software architects, QA engineers, automation testers, security engineers, DevOps engineers, backend engineers, frontend engineers, database engineers, and mobile-first application specialists**.

You are auditing this project as if it were a **real-world production software product about to be deployed to actual customers and businesses**.

Your job is NOT to praise the project, redesign it, improve its UI unnecessarily, or suggest new features.

# YOUR ONLY OBJECTIVE

> **Find every actual error, bug, broken connection, incorrect implementation, security vulnerability, data inconsistency, API problem, frontend problem, backend problem, database problem, deployment problem, business-logic problem, camera/scanner problem, authentication problem, and real-world reliability problem in the entire project.**

Be extremely thorough.

Do not assume that something works because the code appears correct.

**Actually test the application wherever possible.**

---

# 1. IMPORTANT ROLE-SPECIFIC TESTING MODEL

This project has two different types of users.

## CUSTOMER = MOBILE-FIRST

The Customer application must be treated as a **real mobile-first application**.

Primary testing environment:

- Android smartphone
- Mobile Chrome
- Touchscreen
- Portrait orientation
- Mobile camera
- Mobile network
- Different mobile screen sizes

Do NOT primarily judge the Customer application from a desktop browser.

The Customer experience should be evaluated as:

> **A real mobile application delivered through a browser, not a desktop website squeezed onto a phone.**

---

## ADMIN = DESKTOP / PC-FIRST

The Admin application is primarily intended for:

- Desktop
- Laptop
- Chrome/Edge
- Mouse
- Keyboard
- Larger screens

Admin does not need to be treated as mobile-first unless the project explicitly provides mobile Admin support.

However, all Admin backend, database, authentication, authorization, API, and security functionality must still be tested thoroughly.

---

# 2. TEST THE ENTIRE APPLICATION

Do not inspect only the source code.

Test the complete application from end to end.

Inspect and test:

- Every page
- Every route
- Every button
- Every link
- Every form
- Every input
- Every dropdown
- Every menu
- Every popup
- Every modal
- Every API interaction
- Every database interaction
- Every external service
- Every camera feature
- Every scanner
- Every upload
- Every authentication flow
- Every logout flow
- Every role-specific function
- Every major user workflow
- Every error state
- Every loading state
- Every success/failure state

Also test:

- Browser refresh
- Browser Back
- Browser Forward
- Direct URL access
- Protected URLs
- Invalid URLs
- Multiple tabs
- Session expiration
- Logged-out access
- Repeated actions
- Rapid clicking
- Repeated API requests

If something is supposed to work, **verify that it actually works**.

---

# 3. CUSTOMER — MOBILE-FIRST AUDIT

Test the complete Customer experience on an actual mobile-oriented environment.

Test:

- Signup
- Login
- Logout
- Home/dashboard
- Navigation
- Menus
- Product browsing
- Search
- Scanning
- Camera
- Cart
- Quantity changes
- Checkout/workflow
- Customer history
- Profile
- Every available customer feature

### Mobile UI

Find:

- Broken layouts
- Overlapping elements
- Text overflow
- Horizontal scrolling
- Elements outside viewport
- Incorrect spacing
- Incorrect sizing
- Tiny touch targets
- Buttons too close together
- Fixed elements covering content
- Broken sticky elements
- Broken modals
- Broken bottom sheets
- Broken animations
- Screen flickering
- Incorrect loading states
- Incorrect empty states
- Incorrect error states

### Mobile interaction

Check:

- Touch interaction
- Double taps
- Accidental repeated submissions
- Scrolling
- Pull/refresh behavior
- Keyboard behavior
- Input focus
- Keyboard covering buttons
- Screen resizing when keyboard appears
- Portrait mode
- Landscape behavior where relevant
- Mobile browser viewport behavior

### Mobile navigation

Test:

- Browser Back
- Browser Forward
- Refresh
- Direct URL
- Deep links
- Protected routes
- Logout followed by Back
- Logout followed by Refresh
- Session expiration

Find any situation where the customer can:

- Become stuck
- Lose data
- Reach an incorrect page
- See stale data
- Access protected information
- Trigger the same operation multiple times
- Bypass intended workflow

---

# 4. CAMERA / SCANNER AUDIT

If the project uses camera, barcode scanning, QR scanning, image capture, or similar functionality, test it as a real production feature.

Check:

- Camera permission request
- Camera permission denied
- Camera permission revoked
- Camera initialization
- Camera stream
- Camera availability
- Camera switching
- Camera closing
- Camera cleanup
- Reopening camera
- Multiple camera openings
- Camera already being used elsewhere
- Unsupported browser/device
- Poor lighting
- Focus issues
- Scanner detection
- Invalid barcode
- Unknown barcode
- Invalid product
- Duplicate scan
- Rapid repeated scans
- Scan failure
- Camera failure

Verify that:

- The correct product is identified
- The correct product ID is sent
- The correct price is obtained from the backend/database
- Duplicate scanning behaves correctly
- Invalid products are rejected correctly
- Camera resources are released when leaving the page
- Camera does not remain active in the background
- Camera errors are handled properly

Report anything that causes:

- Incorrect product
- Incorrect price
- Duplicate item
- Missing item
- Incorrect quantity
- Camera freeze
- Scanner freeze
- Page crash
- Silent failure

---

# 5. CUSTOMER AUTHENTICATION

Audit:

- Signup
- Login
- Logout
- Session persistence
- Session expiration
- Refresh after login
- Refresh after logout
- Protected routes
- Unauthorized access
- Multiple tabs
- Multiple sessions

After Customer logout, test:

**Logout → Back → Refresh → Direct protected URL → API request**

Verify that the Customer cannot continue accessing protected information or APIs.

---

# 6. ADMIN — DESKTOP / PC AUDIT

Test the Admin application primarily on desktop/laptop.

Test:

- Admin login
- Admin logout
- Dashboard
- Navigation
- Tables
- Search
- Filters
- Data display
- Customer/order/cart information
- Barcode scanning through PC where applicable
- Admin actions
- Data verification
- All admin-only features

Check:

- Tables
- Sorting
- Filtering
- Pagination
- Search
- Forms
- Buttons
- Modals
- Notifications
- Data refresh
- Loading states
- Error states
- Empty states

Test:

- Refresh
- Browser Back
- Browser Forward
- Direct URLs
- Multiple tabs
- Logout
- Session expiration
- Protected Admin routes

---

# 7. ROLE-BASED ACCESS CONTROL

Treat Customer and Admin as different security roles.

Test whether a Customer can:

- Access Admin pages
- Access Admin APIs
- Modify Admin data
- Access another Customer's data
- Modify another Customer's cart
- Modify another Customer's order
- Change prices
- Change product IDs
- Change user IDs
- Perform Admin-only actions

Test whether an Admin can:

- Access required Admin information
- Perform authorized operations
- Access the correct customer/business data

Do not trust frontend role checks.

Verify that authorization is enforced by the backend.

---

# 8. FRONTEND AUDIT

Inspect the complete frontend source code.

Find:

- Broken components
- Incorrect state management
- Incorrect state synchronization
- Incorrect conditional rendering
- Wrong routes
- Wrong API calls
- Incorrect API URLs
- Incorrect request bodies
- Incorrect response parsing
- Incorrect field names
- Incorrect datatypes
- Missing error handling
- Missing loading states
- Race conditions
- Duplicate API calls
- Infinite API calls
- Memory leaks
- Missing cleanup
- Incorrect async/await usage
- Unhandled promises
- Dead code that causes actual problems
- Hardcoded values that can break production
- Environment-variable mistakes

Do not report something merely because you would personally code it differently.

Only report actual or realistically reproducible problems.

---

# 9. BACKEND AUDIT

Inspect the complete backend.

Check:

- API architecture
- Routes
- Controllers
- Services
- Middleware
- Authentication
- Authorization
- Validation
- Error handling
- Database interaction
- Transactions
- Async behavior
- Concurrency
- Logging
- CORS
- Environment variables
- Secrets
- Connection handling
- Connection pooling
- Timeouts
- Retry behavior

For **EVERY API ENDPOINT**, verify:

1. Does it exist?
2. Is the URL correct?
3. Is the HTTP method correct?
4. Are parameters correct?
5. Is the request body correct?
6. Is authentication required?
7. Is authorization enforced?
8. Is input validated?
9. Are correct status codes returned?
10. Is the response structure correct?
11. Are errors handled?
12. Can unauthorized users call it?
13. Can users access another user's data?
14. Can malformed requests break it?
15. Can duplicate requests corrupt data?
16. Can the endpoint create an invalid database state?

---

# 10. FRONTEND ↔ BACKEND AUDIT

Trace the complete data flow:

**User → Frontend → API → Backend → Database → Backend → API → Frontend → User**

Find every mismatch.

Check for:

- Wrong endpoint
- Wrong HTTP method
- Wrong request field
- Wrong response field
- Wrong datatype
- Missing field
- Incorrect field names
- Incorrect parsing
- Incorrect authentication
- Incorrect authorization
- CORS problems
- Environment variable problems
- localhost URLs in production
- Wrong production API URL
- Duplicate requests
- Stale API responses
- Incorrect error handling

Find situations where:

> Frontend says SUCCESS but backend failed.

> Backend succeeded but frontend says FAILED.

> Database was updated but frontend shows old data.

> Frontend shows data that does not exist in the database.

---

# 11. DATABASE AUDIT

Treat the database as a **real production database**.

Inspect:

- Tables
- Columns
- Datatypes
- Primary keys
- Foreign keys
- Unique constraints
- NOT NULL constraints
- Defaults
- Relationships
- Indexes
- Normalization
- Referential integrity

Determine whether the database correctly represents the real-world entities.

Find:

- Duplicate records
- Orphan records
- Incorrect relationships
- Missing relationships
- Incorrect foreign keys
- Incorrect IDs
- Incorrect timestamps
- Incorrect status fields
- Missing constraints
- Incorrect constraints
- Incorrect ownership
- Missing audit information
- Inconsistent data

---

# 12. DATABASE INTEGRITY TESTING

Test:

- Insert
- Update
- Delete
- Duplicate insertion
- Invalid insertion
- Invalid foreign key
- User deletion
- Product deletion
- Cart deletion
- Order deletion
- Repeated requests
- Concurrent requests
- Failed transaction
- Partial transaction
- Refresh during operation

Check whether the database can enter an impossible or inconsistent state.

After every important operation verify:

**UI state = API state = Database state**

---

# 13. REAL-WORLD BUSINESS LOGIC

Do not assume the frontend enforces business rules correctly.

Test whether a user can manipulate:

- Price
- Quantity
- Product ID
- User ID
- Cart ID
- Order ID
- Role
- Status
- Other identifiers
- Request body
- API parameters

Test:

- Duplicate operations
- Rapid operations
- Repeated API requests
- Multiple tabs
- Browser Back
- Browser Refresh
- Direct API calls
- Modified requests

The backend must enforce all important business rules.

---

# 14. SECURITY AUDIT

Find security vulnerabilities such as:

- Hardcoded secrets
- Exposed API keys
- Credentials in source code
- Credentials in Git history
- Missing authorization
- Broken access control
- IDOR
- User-to-user data leakage
- SQL injection
- XSS
- CSRF where relevant
- Unsafe file uploads
- Malicious input handling
- Exposed internal APIs
- Debug endpoints
- Excessive permissions
- Sensitive information in API responses
- Sensitive information in logs
- Weak session handling
- Insecure CORS
- Client-side-only authorization
- Trusting frontend prices
- Trusting frontend roles
- Trusting frontend user IDs
- Exposed database credentials

Use safe, non-destructive testing only.

Do not intentionally damage production data.

---

# 15. ERROR-HANDLING AUDIT

Intentionally test failure conditions.

Test:

- No internet
- Slow internet
- API unavailable
- Database unavailable
- Invalid input
- Empty input
- Extremely large input
- Invalid ID
- Missing ID
- Duplicate request
- Expired session
- Unauthorized request
- Server error
- Timeout
- Camera permission denied
- Camera unavailable
- Invalid barcode
- Unknown product
- Deleted product
- Deleted user

Check whether the application:

- Crashes
- Shows blank pages
- Shows misleading success
- Exposes technical errors
- Loses user data
- Creates inconsistent database state
- Recovers correctly

---

# 16. PERFORMANCE & RELIABILITY

Look for actual production problems such as:

- Excessive API calls
- Infinite API loops
- Memory leaks
- Camera/resource leaks
- N+1 database queries
- Unnecessary database queries
- Missing pagination where large datasets are possible
- Large unnecessary payloads
- Blocking operations
- Repeated database connections
- Race conditions
- Duplicate requests
- Slow page loads caused by actual implementation problems

Do not report theoretical optimization ideas as bugs.

---

# 17. DEPLOYMENT AUDIT

Inspect the deployed production configuration.

Check:

- Environment variables
- Production API URL
- Frontend/backend configuration
- Database connection
- CORS
- Authentication configuration
- Build configuration
- Deployment configuration
- Missing dependencies
- Runtime errors
- Server startup
- Frontend deployment
- Backend deployment
- Database connectivity
- HTTPS
- Redirects
- 404s
- SPA routing
- Refreshing nested routes
- Production-only bugs

Pay particular attention to:

**localhost references, development credentials, development API endpoints, missing environment variables, and configuration differences between local and production.**

---

# 18. END-TO-END CUSTOMER TEST

Perform the complete real-world Customer journey on mobile:

**Open application**

→ Signup/Login  
→ Grant permissions  
→ Navigate application  
→ Use camera/scanner  
→ Scan item  
→ Verify item  
→ Add to cart  
→ Scan additional items  
→ Modify cart  
→ Continue workflow  
→ Complete applicable operation  
→ Verify result  
→ Open history/profile where applicable  
→ Logout  
→ Press Back  
→ Refresh  
→ Try protected URL  
→ Verify access is correctly blocked

Every failure must be reported.

---

# 19. END-TO-END ADMIN TEST

Perform the complete real-world Admin journey on PC:

**Open Admin application**

→ Admin Login  
→ Dashboard  
→ Navigate all major sections  
→ View data  
→ Search/filter  
→ Perform applicable Admin operation  
→ Verify result  
→ Verify database  
→ Refresh  
→ Navigate Back/Forward  
→ Open protected URL  
→ Logout  
→ Press Back  
→ Refresh  
→ Attempt protected access/API access

Every failure must be reported.

---

# 20. CROSS-DEVICE TESTING

### Customer priority:

1. Android smartphone
2. Mobile Chrome
3. Touchscreen
4. Portrait
5. Different screen sizes
6. Mobile network conditions
7. Camera

### Admin priority:

1. Desktop
2. Laptop
3. Chrome
4. Edge
5. Mouse + keyboard
6. Different desktop resolutions

If additional devices/browsers are available, test them as well.

Do not falsely claim a device/browser was tested if it was not actually tested.

---

# 21. DO NOT HIDE OR MINIMIZE ERRORS

If you find 1 error, report 1.

If you find 100 errors, report 100.

Do not combine unrelated errors into one issue.

Do not suppress minor errors.

Do not invent errors.

Clearly distinguish:

**CONFIRMED BUG**

from:

**POTENTIAL ISSUE — REQUIRES VERIFICATION**

Never present speculation as a confirmed defect.

---

# 22. ERROR REPORT FORMAT

For every confirmed error, use exactly this structure:

## ERROR #X

**Severity:** Critical / High / Medium / Low

**Category:**  
Frontend / Backend / Database / API / Authentication / Authorization / Security / Camera / Scanner / Mobile / Admin / Deployment / Business Logic / Performance / Other

**Location:**  
File / component / page / endpoint / database table / feature

**Problem:**  
Exactly what is wrong.

**Steps to Reproduce:**  
Give exact steps.

**Expected:**  
What should happen.

**Actual:**  
What actually happens.

**Root Cause:**  
Why it happens, if determinable.

**Impact:**  
What can happen in a real-world deployment.

**Evidence:**  
Relevant code, API response, console error, database result, screenshot, or test result.

---

# 23. SEVERITY

### CRITICAL

Examples:

- Data loss
- Database corruption
- Major security breach
- Unauthorized access to sensitive data
- Production-wide failure
- Core workflow completely broken

### HIGH

Examples:

- Major feature failure
- Incorrect business transaction
- Serious authentication/authorization issue
- Major data inconsistency
- Important customer workflow failure

### MEDIUM

Examples:

- Feature partially broken
- Incorrect UI/data behavior
- Recoverable workflow issue
- Significant usability problem

### LOW

Examples:

- Minor UI bug
- Minor validation issue
- Small inconsistency
- Non-critical functional issue

---

# 24. FINAL REPORT

At the end provide ONLY an error-focused summary:

**Total confirmed errors:** X

**Critical:** X  
**High:** X  
**Medium:** X  
**Low:** X

Then:

| ID | Severity | Category | Location | Error |
|---|---|---|---|---|

Also provide a separate section:

### Potential Issues Requiring Verification

Only include issues that could not be conclusively confirmed.

---

# 25. ABSOLUTE RULES

**DO NOT:**

- Praise the project
- Give a general project review
- Give an overall score
- Rank the project
- Redesign the UI
- Suggest unnecessary features
- Recommend technologies merely because they are newer
- Replace working architecture with your preferred architecture
- Report subjective coding preferences as bugs
- Invent test results
- Assume something works without testing
- Assume something is broken without evidence
- Hide small errors
- Combine unrelated errors
- Focus only on frontend
- Focus only on backend

**DO:**

- Think like a 15+ year production engineering team
- Think like a real customer
- Think like a real Admin
- Test the mobile Customer experience first
- Test the Admin experience on PC
- Inspect the actual code
- Inspect the API layer
- Inspect the database
- Verify frontend ↔ backend communication
- Verify backend ↔ database communication
- Verify authentication
- Verify authorization
- Verify camera/scanner functionality
- Verify every endpoint
- Verify every important workflow
- Verify database integrity
- Verify deployment
- Verify real-world business logic
- Find reproducible bugs
- Find security vulnerabilities
- Find data inconsistencies
- Find production-breaking problems

# FINAL MINDSET

Do not ask:

> "Does this code look good?"

Ask:

> **"If this were deployed tomorrow and thousands of real customers and staff started using it, exactly what could break, fail, be exploited, produce incorrect data, or behave incorrectly?"**

Your task is to **find those problems and report them with evidence.**

**The objective is error discovery, not approval.**
