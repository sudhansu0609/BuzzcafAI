document.addEventListener("DOMContentLoaded", () => {
    // Application State
    let state = {
        brands: [],
        workflows: [],
        projects: [],
        selectedProjectId: null,
        activeTab: "dashboard"
    };

    // DOM Elements Cache
    const el = {
        navItems: document.querySelectorAll(".nav-item"),
        tabContents: document.querySelectorAll(".tab-content"),
        pageTitle: document.getElementById("page-title"),
        systemStatus: document.querySelector(".system-status-indicator .status-label"),
        systemStatusDot: document.querySelector(".system-status-indicator .status-dot"),
        
        // Stats
        statTotal: document.getElementById("stat-total-projects"),
        statActive: document.getElementById("stat-active-projects"),
        statCompleted: document.getElementById("stat-completed-projects"),
        
        // Project Form
        createProjectForm: document.getElementById("create-project-form"),
        projName: document.getElementById("proj-name"),
        projBrand: document.getElementById("proj-brand"),
        projWorkflow: document.getElementById("proj-workflow"),
        
        // Lists
        recentProjectsList: document.getElementById("recent-projects-list"),
        projectsSidebarList: document.getElementById("projects-sidebar-list"),
        projectSearchInput: document.getElementById("project-search-input"),
        
        // Workspace
        projectWorkspace: document.getElementById("project-workspace"),
        
        // Settings Form
        settingsForm: document.getElementById("settings-form"),
        settingsGeminiKey: document.getElementById("settings-gemini-key"),
        settingsGeminiModel: document.getElementById("settings-gemini-model"),
        settingsLmsUrl: document.getElementById("settings-lms-url"),
        settingsLmsModel: document.getElementById("settings-lms-model"),
        settingsPreferGemini: document.getElementById("settings-prefer-gemini"),
        
        // Modals
        modalViewer: document.getElementById("modal-viewer"),
        modalTitle: document.getElementById("modal-title"),
        modalBodyContent: document.getElementById("modal-body-content"),
        modalClose: document.querySelector(".close-modal")
    };

    // --- Tab Navigation ---
    el.navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const tabId = item.getAttribute("data-tab");
            switchTab(tabId);
        });
    });

    function switchTab(tabId) {
        state.activeTab = tabId;
        el.navItems.forEach(nav => nav.classList.remove("active"));
        document.querySelector(`.nav-item[data-tab="${tabId}"]`).classList.add("active");
        
        el.tabContents.forEach(tab => tab.classList.remove("active"));
        document.getElementById(`tab-${tabId}`).classList.add("active");
        
        // Update header title
        if (tabId === "dashboard") {
            el.pageTitle.textContent = "Media Production Dashboard";
            loadDashboardData();
        } else if (tabId === "projects") {
            el.pageTitle.textContent = "Production Workspace";
            loadProjectsTab();
        } else if (tabId === "settings") {
            el.pageTitle.textContent = "System Configuration";
            loadSettings();
        }
    }

    // --- API Interactions ---
    async function apiRequest(url, method = "GET", body = null) {
        const options = {
            method,
            headers: { "Content-Type": "application/json" }
        };
        if (body) {
            options.body = JSON.stringify(body);
        }
        
        setLoadingState(true);
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const errText = await response.text();
                throw new Error(errText || response.statusText);
            }
            return await response.json();
        } catch (error) {
            console.error(`API Error: ${error.message}`);
            alert(`API Error: ${error.message}`);
            return null;
        } finally {
            setLoadingState(false);
        }
    }

    function setLoadingState(isLoading) {
        if (isLoading) {
            el.systemStatus.textContent = "Engine Busy";
            el.systemStatusDot.className = "status-dot green pulse";
        } else {
            el.systemStatus.textContent = "Engine Idle";
            el.systemStatusDot.className = "status-dot green";
        }
    }

    // --- Initial Core Loading ---
    async function initializeApp() {
        // Load Brands & Workflows for forms
        const brands = await apiRequest("/api/brands");
        if (brands) {
            state.brands = brands;
            el.projBrand.innerHTML = brands.map(b => `<option value="${b}">${b}</option>`).join("");
        }
        
        const workflows = await apiRequest("/api/workflows");
        if (workflows) {
            state.workflows = workflows;
            el.projWorkflow.innerHTML = workflows.map(w => `<option value="${w.id}">${w.name}</option>`).join("");
        }

        // Initialize dashboard view
        loadDashboardData();
        loadSettings();
    }

    // --- Dashboard logic ---
    async function loadDashboardData() {
        const projects = await apiRequest("/api/projects");
        if (projects) {
            state.projects = projects;
            updateStats(projects);
            renderRecentActivity(projects);
        }
    }

    function updateStats(projects) {
        const total = projects.length;
        const active = projects.filter(p => p.status === "active").length;
        const completed = projects.filter(p => p.status === "completed").length;
        
        el.statTotal.textContent = total;
        el.statActive.textContent = active;
        el.statCompleted.textContent = completed;
    }

    function renderRecentActivity(projects) {
        if (projects.length === 0) {
            el.recentProjectsList.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-square-poll-horizontal" style="font-size: 32px; display:block; margin-bottom:10px;"></i>
                    No active production pipelines. Create a project to start.
                </div>`;
            return;
        }
        
        el.recentProjectsList.innerHTML = projects.slice(0, 5).map(p => `
            <div class="project-activity-card" data-id="${p.id}">
                <div class="activity-info">
                    <span class="activity-name">${p.name}</span>
                    <span class="activity-meta">
                        <span class="badge brand">${p.brand}</span>
                        Step: <strong>${p.current_step}</strong>
                    </span>
                </div>
                <div>
                    <span class="badge status-${p.status}">${p.status}</span>
                </div>
            </div>
        `).join("");

        // Setup click selectors
        el.recentProjectsList.querySelectorAll(".project-activity-card").forEach(card => {
            card.addEventListener("click", () => {
                state.selectedProjectId = card.getAttribute("data-id");
                switchTab("projects");
            });
        });
    }

    // Create New Project Form Submit
    el.createProjectForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
            name: el.projName.value.trim(),
            brand: el.projBrand.value,
            workflow_name: el.projWorkflow.value
        };
        
        const newProj = await apiRequest("/api/projects", "POST", payload);
        if (newProj) {
            el.projName.value = "";
            state.selectedProjectId = newProj.id;
            switchTab("projects");
        }
    });

    // --- Projects Workspace Tab Logic ---
    async function loadProjectsTab() {
        const projects = await apiRequest("/api/projects");
        if (projects) {
            state.projects = projects;
            renderProjectsSidebarList(projects);
            if (state.selectedProjectId) {
                selectProject(state.selectedProjectId);
            } else if (projects.length > 0) {
                selectProject(projects[0].id);
            } else {
                renderEmptyWorkspace();
            }
        }
    }

    function renderProjectsSidebarList(projects) {
        const searchVal = el.projectSearchInput.value.toLowerCase().trim();
        const filtered = projects.filter(p => p.name.toLowerCase().includes(searchVal) || p.brand.toLowerCase().includes(searchVal));
        
        if (filtered.length === 0) {
            el.projectsSidebarList.innerHTML = `<div class="empty-state">No matching projects</div>`;
            return;
        }

        el.projectsSidebarList.innerHTML = filtered.map(p => `
            <div class="sidebar-project-item ${state.selectedProjectId === p.id ? 'active' : ''}" data-id="${p.id}">
                <h4>${p.name}</h4>
                <div class="meta-row">
                    <span class="badge brand">${p.brand}</span>
                    <span>${p.current_step}</span>
                </div>
            </div>
        `).join("");

        el.projectsSidebarList.querySelectorAll(".sidebar-project-item").forEach(item => {
            item.addEventListener("click", () => {
                const pid = item.getAttribute("data-id");
                selectProject(pid);
            });
        });
    }

    el.projectSearchInput.addEventListener("input", () => {
        renderProjectsSidebarList(state.projects);
    });

    function renderEmptyWorkspace() {
        el.projectWorkspace.innerHTML = `
            <div class="empty-workspace">
                <i class="fa-solid fa-folder-open large-icon"></i>
                <h3>No projects found in the studio</h3>
                <p>Return to the dashboard to create your first production project.</p>
            </div>`;
    }

    async function selectProject(projectId) {
        state.selectedProjectId = projectId;
        
        // Highlight active item in sidebar
        document.querySelectorAll(".sidebar-project-item").forEach(item => {
            if (item.getAttribute("data-id") === projectId) {
                item.classList.add("active");
            } else {
                item.classList.remove("active");
            }
        });

        // Load complete project details
        const project = await apiRequest(`/api/projects/${projectId}`);
        if (project) {
            renderWorkspace(project);
        }
    }

    function renderWorkspace(project) {
        const wf = state.workflows.find(w => w.id === project.workflow_name);
        if (!wf) return;

        // Find active step state in execution history
        let currentStepStatus = "pending";
        let activeHist = project.steps_history.find(h => h.step_name === project.current_step && h.status !== "completed");
        if (activeHist) {
            currentStepStatus = activeHist.status;
        }

        // Render Workspace layout HTML
        el.projectWorkspace.innerHTML = `
            <div class="workspace-header">
                <div class="workspace-title">
                    <h2>${project.name}</h2>
                    <p>Brand Channel: <strong>${project.brand}</strong> &bull; Core Pipeline: <strong>${wf.name}</strong></p>
                </div>
                <div>
                    <span class="badge status-${project.status}">${project.status}</span>
                </div>
            </div>

            <!-- Workflow Graph Display -->
            <div class="pipeline-container">
                <h3>Production Workflow Steps</h3>
                <div class="pipeline-flow">
                    ${wf.steps.map((step, idx) => {
                        let nodeClass = "pending";
                        const stepHist = project.steps_history.find(h => h.step_name === step.name);
                        
                        if (stepHist) {
                            if (stepHist.status === "completed") {
                                nodeClass = "completed";
                            } else if (stepHist.status === "paused_for_approval") {
                                nodeClass = "paused_for_approval";
                            } else if (stepHist.status === "running") {
                                nodeClass = "active";
                            }
                        } else if (project.current_step === step.name) {
                            nodeClass = "active";
                        }
                        
                        let arrow = idx < wf.steps.length - 1 ? `<div class="pipeline-arrow"><i class="fa-solid fa-arrow-right"></i></div>` : "";
                        
                        return `
                            <div class="pipeline-node ${nodeClass}">
                                <div class="node-name">${step.name}</div>
                                <div class="node-role">${step.agent_role.replace("Agent", "")}</div>
                            </div>
                            ${arrow}
                        `;
                    }).join("")}
                </div>
            </div>

            <!-- Execution Panel -->
            <div class="execution-controls-panel">
                <div class="execution-banner">
                    <div class="execution-state-text">
                        ${project.status === "completed" ? `
                            <h4><i class="fa-solid fa-circle-check text-green" style="color:var(--color-green)"></i> Production Pipeline Complete</h4>
                            <p>All scripts, layouts, and metadata have been written and archived.</p>
                        ` : `
                            <h4>Active Step: <span class="text-gold" style="color:var(--accent-gold)">${project.current_step}</span></h4>
                            <p>Agent in charge: <strong>${wf.steps.find(s => s.name === project.current_step)?.agent_role || "CEO"}</strong></p>
                        `}
                    </div>
                    
                    <div class="execution-actions">
                        ${project.status === "completed" ? "" : 
                          currentStepStatus === "paused_for_approval" ? `
                            <button id="btn-approve" class="btn btn-primary"><i class="fa-solid fa-thumbs-up"></i> Approve Asset</button>
                            <button id="btn-revision" class="btn btn-secondary"><i class="fa-solid fa-edit"></i> Request Revisions</button>
                          ` : `
                            <button id="btn-run" class="btn btn-primary"><i class="fa-solid fa-play"></i> Run Agent Step</button>
                          `
                        }
                    </div>
                </div>

                ${currentStepStatus === "paused_for_approval" ? `
                    <div class="feedback-input-area">
                        <textarea id="feedback-text" class="form-group feedback-textarea" placeholder="Add revision notes for the Agent here... (e.g. Make the intro more dramatic, correct dates, change thumbnail hook)"></textarea>
                    </div>
                ` : ""}
            </div>

            <!-- Assets & Outlines Generated -->
            <div class="outputs-panel">
                <h3>Generated Production Artifacts</h3>
                ${Object.keys(project.assets).length === 0 ? `
                    <div class="empty-state">No assets generated yet. Run the first step (Research) to populate details.</div>
                ` : `
                    <div style="display:flex; flex-direction:column; gap:16px;">
                        ${Object.entries(project.assets).map(([key, filename]) => `
                            <div class="project-activity-card" data-asset="${key}">
                                <div style="display:flex; align-items:center; gap:12px;">
                                    <i class="fa-solid ${filename.endsWith('.json') ? 'fa-file-code' : 'fa-file-signature'}" style="font-size:20px; color:var(--accent-gold)"></i>
                                    <div>
                                        <div style="font-weight:600; font-size:14px; text-transform:capitalize;">${key.replace("_", " ")}</div>
                                        <div style="font-size:11px; color:var(--text-muted)">File: ${filename}</div>
                                    </div>
                                </div>
                                <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); window.viewAsset('${project.id}', '${key}')">View Asset</button>
                            </div>
                        `).join("")}
                    </div>
                `}
            </div>
        `;

        // Event Listeners for actions
        const btnRun = document.getElementById("btn-run");
        if (btnRun) {
            btnRun.addEventListener("click", () => executeWorkflowStep(project.id));
        }

        const btnApprove = document.getElementById("btn-approve");
        if (btnApprove) {
            btnApprove.addEventListener("click", () => executeWorkflowStep(project.id));
        }

        const btnRevision = document.getElementById("btn-revision");
        if (btnRevision) {
            btnRevision.addEventListener("click", () => {
                const feedback = document.getElementById("feedback-text").value.trim();
                if (!feedback) {
                    alert("Please enter feedback explaining the required changes before requesting revisions.");
                    return;
                }
                executeWorkflowStep(project.id, feedback);
            });
        }
    }

    async function executeWorkflowStep(projectId, feedback = null) {
        setLoadingState(true);
        const payload = feedback ? { feedback } : {};
        const project = await apiRequest(`/api/projects/${projectId}/execute`, "POST", payload);
        if (project) {
            // Reload project info
            state.projects = state.projects.map(p => p.id === projectId ? project : p);
            renderWorkspace(project);
            renderProjectsSidebarList(state.projects);
        }
        setLoadingState(false);
    }

    // Global utility to fetch and display asset in a modal
    window.viewAsset = async (projectId, assetKey) => {
        const asset = await apiRequest(`/api/projects/${projectId}/asset/${assetKey}`);
        if (!asset) return;

        el.modalTitle.textContent = `${assetKey.toUpperCase().replace("_", " ")} Asset`;
        
        let htmlContent = "";
        
        if (asset.content) {
            // Markdown basic parse
            htmlContent = parseMarkdown(asset.content);
        } else {
            // JSON format
            htmlContent = `<pre><code>${JSON.stringify(asset, null, 4)}</code></pre>`;
        }
        
        el.modalBodyContent.innerHTML = htmlContent;
        el.modalViewer.style.display = "block";
    };

    // Close Modal
    el.modalClose.addEventListener("click", () => {
        el.modalViewer.style.display = "none";
    });
    window.addEventListener("click", (e) => {
        if (e.target === el.modalViewer) {
            el.modalViewer.style.display = "none";
        }
    });

    // Simple markdown parsing implementation for visual display
    function parseMarkdown(md) {
        let html = md;
        // Headers
        html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
        html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
        html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
        // Bold
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Bullet points
        html = html.replace(/^\- (.*?)$/gm, '<li>$1</li>');
        html = html.replace(/^  \- (.*?)$/gm, '<li style="margin-left: 20px;">$1</li>');
        // Lines
        html = html.replace(/
/g, '<br>');
        
        return `<div class="md-rendered-view">${html}</div>`;
    }

    // --- Settings tab logic ---
    async function loadSettings() {
        const settings = await apiRequest("/api/settings");
        if (settings) {
            el.settingsGeminiKey.value = settings.gemini_api_key || "";
            el.settingsGeminiModel.value = settings.gemini_model || "gemini-1.5-flash";
            el.settingsLmsUrl.value = settings.lm_studio_url || "http://localhost:1234/v1";
            el.settingsLmsModel.value = settings.lm_studio_model || "";
            el.settingsPreferGemini.checked = settings.prefer_gemini;
        }
    }

    el.settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
            gemini_api_key: el.settingsGeminiKey.value.trim(),
            gemini_model: el.settingsGeminiModel.value.trim(),
            lm_studio_url: el.settingsLmsUrl.value.trim(),
            lm_studio_model: el.settingsLmsModel.value.trim(),
            prefer_gemini: el.settingsPreferGemini.checked
        };
        
        const res = await apiRequest("/api/settings", "POST", payload);
        if (res && res.status === "success") {
            alert("LLM settings saved and connection registry reloaded.");
        }
    });

    // Run app
    initializeApp();
});
