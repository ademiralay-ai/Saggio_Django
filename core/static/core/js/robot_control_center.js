(function () {
    const boot = window.RCC_BOOT || {};
    const urls = boot.urls || {};
    const csrf = boot.csrf || "";

    const state = {
        agents: Array.isArray(boot.agents) ? boot.agents : [],
        processes: Array.isArray(boot.processes) ? boot.processes : [],
        releases: Array.isArray(boot.releases) ? boot.releases : [],
        refreshTimer: null,
    };

    const el = {
        totalAgents: document.getElementById("rcc-total-agents"),
        onlineAgents: document.getElementById("rcc-online-agents"),
        runningJobs: document.getElementById("rcc-running-jobs"),
        queuedJobs: document.getElementById("rcc-queued-jobs"),
        agentsWrap: document.getElementById("rcc-agents"),
        jobsBody: document.getElementById("rcc-jobs-body"),
        refreshBtn: document.getElementById("rcc-refresh-btn"),
        limit: document.getElementById("rcc-job-limit"),
        jobSearch: document.getElementById("rcc-job-search"),
        jobStatus: document.getElementById("rcc-job-status"),
        jobAgentFilter: document.getElementById("rcc-job-agent-filter"),
        form: document.getElementById("rcc-dispatch-form"),
        commandType: document.getElementById("rcc-command-type"),
        processWrap: document.getElementById("rcc-process-wrap"),
        processId: document.getElementById("rcc-process-id"),
        agentCode: document.getElementById("rcc-agent-code"),
        priority: document.getElementById("rcc-priority"),
        command: document.getElementById("rcc-command"),
        note: document.getElementById("rcc-note"),

        agentForm: document.getElementById("rcc-agent-form"),
        agentNewCode: document.getElementById("rcc-agent-new-code"),
        agentNewName: document.getElementById("rcc-agent-new-name"),
        agentNewToken: document.getElementById("rcc-agent-new-token"),
        agentEnabled: document.getElementById("rcc-agent-enabled"),
        agentDesired: document.getElementById("rcc-agent-desired"),

        releaseForm: document.getElementById("rcc-release-form"),
        releaseVersion: document.getElementById("rcc-release-version"),
        releaseUrl: document.getElementById("rcc-release-url"),
        releaseFile: document.getElementById("rcc-release-file"),
        releaseSha: document.getElementById("rcc-release-sha"),
        releaseInstallCmd: document.getElementById("rcc-release-install-cmd"),
        releaseNotes: document.getElementById("rcc-release-notes"),
        releaseActive: document.getElementById("rcc-release-active"),
        releaseMandatory: document.getElementById("rcc-release-mandatory"),
        releaseBody: document.getElementById("rcc-release-body"),
        desiredVersion: document.getElementById("rcc-desired-version"),
        desiredAgent: document.getElementById("rcc-desired-agent"),
        setDesiredBtn: document.getElementById("rcc-set-desired-btn"),
        deployVersion: document.getElementById("rcc-deploy-version"),
        deployScope: document.getElementById("rcc-deploy-scope"),
        deployAgent: document.getElementById("rcc-deploy-agent"),
        deployBtn: document.getElementById("rcc-deploy-btn"),
        buildVersion: document.getElementById("rcc-build-version"),
        buildForce: document.getElementById("rcc-build-force"),
        buildBtn: document.getElementById("rcc-build-btn"),
        buildResult: document.getElementById("rcc-build-result"),
        packageVersion: document.getElementById("rcc-package-version"),
        packageForce: document.getElementById("rcc-package-force"),
        packageBtn: document.getElementById("rcc-package-btn"),
        packageResult: document.getElementById("rcc-package-result"),

        logAgent: document.getElementById("rcc-log-agent"),
        logLimit: document.getElementById("rcc-log-limit"),
        logRefresh: document.getElementById("rcc-log-refresh"),
        logBody: document.getElementById("rcc-log-body"),
    };

    function showToast(msg, type) {
        if (typeof window.showToast === "function") {
            window.showToast(msg, type || "info");
            return;
        }
        console.log(msg);
    }

    function esc(text) {
        return String(text || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function fmtDate(iso) {
        if (!iso) return "-";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return "-";
        return d.toLocaleString("tr-TR", { hour12: false });
    }

    async function getJson(url) {
        const res = await fetch(url, { headers: { "Accept": "application/json" } });
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
    }

    async function postJson(url, body) {
        const res = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf,
            },
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || ("HTTP " + res.status));
        }
        return data;
    }

    async function postForm(url, formData) {
        const res = await fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf,
            },
            body: formData,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            throw new Error(data.error || ("HTTP " + res.status));
        }
        return data;
    }

    function renderAgentOptions() {
        const opts = ['<option value="">Müsait herhangi bir robot</option>'];
        const filterOpts = ['<option value="">Tüm Robotlar</option>'];
        const desiredOpts = ['<option value="">Tüm ajanlara uygula</option>'];
        const logOpts = ['<option value="">Ajan seçin</option>'];
        state.agents.forEach((a) => {
            opts.push(`<option value="${esc(a.code)}">${esc(a.code)} - ${esc(a.name)}</option>`);
            filterOpts.push(`<option value="${esc(a.code)}">${esc(a.code)}</option>`);
            desiredOpts.push(`<option value="${esc(a.code)}">${esc(a.code)} - ${esc(a.name)}</option>`);
            logOpts.push(`<option value="${esc(a.code)}">${esc(a.code)} - ${esc(a.name)}</option>`);
        });
        el.agentCode.innerHTML = opts.join("");
        if (el.jobAgentFilter) el.jobAgentFilter.innerHTML = filterOpts.join("");
        if (el.desiredAgent) el.desiredAgent.innerHTML = desiredOpts.join("");
        if (el.deployAgent) el.deployAgent.innerHTML = ['<option value="">Ajan seçin (single için)</option>', ...desiredOpts.slice(1)].join("");
        if (el.logAgent) el.logAgent.innerHTML = logOpts.join("");
    }

    function renderProcessOptions() {
        const opts = ['<option value="">Süreç seçin</option>'];
        state.processes.forEach((p) => {
            opts.push(`<option value="${p.id}">${esc(p.name)}</option>`);
        });
        el.processId.innerHTML = opts.join("");
    }

    function renderAgents(rows) {
        if (!rows || !rows.length) {
            el.agentsWrap.innerHTML = '<div class="empty-cell">Ajan bulunamadı.</div>';
            return;
        }
        const html = rows.map((a) => {
            const status = String(a.status || "offline").toLowerCase();
            const versionState = String(a.version_state || "ok").toLowerCase();
            const versionCls = versionState === "outdated" ? "outdated" : "online";
            return `
                <div class="rcc-agent-card">
                    <div class="rcc-agent-row">
                        <div>
                            <div class="rcc-agent-code">${esc(a.code)}</div>
                            <div class="rcc-agent-name">${esc(a.name || "-")}</div>
                        </div>
                        <span class="rcc-chip ${status}">${esc(status)}</span>
                    </div>
                    <div class="rcc-agent-meta">
                        <span>Bekleyen iş: ${a.pending_jobs || 0}</span>
                        <span>Son görüldü: ${fmtDate(a.last_seen_at)}</span>
                    </div>
                    <div class="rcc-agent-version">
                        <span>Current: ${esc(a.agent_version || "-")}</span>
                        <span>Desired: ${esc(a.desired_version || "-")}</span>
                        <span class="rcc-chip ${versionCls}">${esc(versionState)}</span>
                    </div>
                </div>
            `;
        }).join("");
        el.agentsWrap.innerHTML = html;
    }

    function renderJobs(rows) {
        if (!rows || !rows.length) {
            el.jobsBody.innerHTML = '<tr><td colspan="10" class="empty-cell">Henüz iş kaydı yok.</td></tr>';
            return;
        }

        let running = 0;
        let queued = 0;

        const html = rows.map((j) => {
            const st = String(j.status || "").toLowerCase();
            if (st === "queued") queued += 1;
            if (st === "running" || st === "dispatched") running += 1;
            const canCancel = ["queued", "dispatched", "running"].includes(st);
            const label = j.target_agent_code || "(otomatik)";
            const process = j.sap_process_name || "-";
            const payload = j.result_payload || {};
            const detailParts = [];
            if (payload.command) detailParts.push("cmd: " + String(payload.command));
            if (payload.stderr) detailParts.push("stderr: " + String(payload.stderr));
            if (payload.stdout) detailParts.push("stdout: " + String(payload.stdout));
            const detailText = detailParts.join("\n\n");
            const msgText = j.result_message || "-";
            const action = canCancel
                ? `<button class="btn btn-sm" data-cancel-job="${j.job_id}"><i class="fas fa-ban"></i> İptal</button>`
                : "-";

            return `
                <tr>
                    <td>#${j.job_id}</td>
                    <td class="rcc-status-cell ${st}">${esc(st)}</td>
                    <td>${esc(j.command_type || "-")}</td>
                    <td>${esc(label)}</td>
                    <td>${esc(process)}</td>
                    <td>${j.priority || 0}</td>
                    <td>${fmtDate(j.started_at || j.created_at)}</td>
                    <td>${fmtDate(j.finished_at)}</td>
                    <td class="rcc-cell-msg" title="${esc(detailText || msgText)}">${esc(msgText)}</td>
                    <td>${action}</td>
                </tr>
            `;
        }).join("");

        el.jobsBody.innerHTML = html;
        el.runningJobs.textContent = String(running);
        el.queuedJobs.textContent = String(queued);

        el.jobsBody.querySelectorAll("[data-cancel-job]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const jobId = btn.getAttribute("data-cancel-job");
                if (!jobId) return;
                btn.disabled = true;
                try {
                    await postJson(urls.cancel, { job_id: Number(jobId), reason: "Panelden iptal edildi" });
                    showToast("İş iptal edildi", "success");
                    await refreshAll();
                } catch (err) {
                    showToast("İptal hatası: " + err.message, "error");
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    function renderReleases(rows) {
        if (!el.releaseBody) return;
        if (!rows || !rows.length) {
            el.releaseBody.innerHTML = '<tr><td colspan="7" class="empty-cell">Release yok.</td></tr>';
            if (el.desiredVersion) el.desiredVersion.innerHTML = '<option value="">Önce release ekleyin</option>';
            if (el.deployVersion) el.deployVersion.innerHTML = '<option value="">Önce release ekleyin</option>';
            return;
        }
        const html = rows.map((r) => `
            <tr>
                <td>${esc(r.version)}</td>
                <td>${r.is_active ? "Evet" : "Hayır"}</td>
                <td>${r.is_mandatory ? "Evet" : "Hayır"}</td>
                <td class="rcc-cell-msg" title="${esc(r.download_url || "")}">${esc(r.download_url || "-")}</td>
                <td>${r.download_path ? `<a class="btn btn-sm" href="${esc(r.download_path)}"><i class="fas fa-download"></i> setup.exe</a>` : "-"}</td>
                <td>${r.package_download_path ? `<a class="btn btn-sm" href="${esc(r.package_download_path)}"><i class="fas fa-file-zipper"></i> paket.zip</a>` : "-"}</td>
                <td>${fmtDate(r.created_at)}</td>
            </tr>
        `).join("");
        el.releaseBody.innerHTML = html;

        const opts = rows.map((r) => `<option value="${esc(r.version)}">${esc(r.version)}</option>`);
        if (el.desiredVersion) el.desiredVersion.innerHTML = opts.join("");
        if (el.deployVersion) el.deployVersion.innerHTML = opts.join("");
    }

    function renderLogs(rows) {
        if (!el.logBody) return;
        if (!rows || !rows.length) {
            el.logBody.innerHTML = '<tr><td colspan="4" class="empty-cell">Kayıt bulunamadı.</td></tr>';
            return;
        }
        const html = rows.map((r) => `
            <tr>
                <td>${fmtDate(r.created_at)}</td>
                <td class="rcc-status-cell ${esc(r.level)}">${esc(r.level)}</td>
                <td>${r.job_id ? "#" + r.job_id : "-"}</td>
                <td>${esc(r.message || "-")}</td>
            </tr>
        `).join("");
        el.logBody.innerHTML = html;
    }

    function updateAgentStats(rows) {
        const total = rows.length;
        const online = rows.filter((a) => ["online", "busy"].includes(String(a.status || "").toLowerCase())).length;
        el.totalAgents.textContent = String(total);
        el.onlineAgents.textContent = String(online);
    }

    async function refreshAgents() {
        const data = await getJson(urls.status);
        const rows = Array.isArray(data.agents) ? data.agents : [];
        state.agents = rows;
        renderAgentOptions();
        renderAgents(rows);
        updateAgentStats(rows);
    }

    async function refreshJobs() {
        const limit = Number(el.limit.value || 50);
        const params = new URLSearchParams({
            limit: String(limit),
            status: String(el.jobStatus?.value || ""),
            agent_code: String(el.jobAgentFilter?.value || ""),
            q: String(el.jobSearch?.value || ""),
        });
        const data = await getJson(urls.jobs + `?${params.toString()}`);
        const rows = Array.isArray(data.jobs) ? data.jobs : [];
        renderJobs(rows);
    }

    async function refreshReleases() {
        const data = await getJson(urls.releases);
        const rows = Array.isArray(data.releases) ? data.releases : [];
        state.releases = rows;
        renderReleases(rows);
    }

    async function refreshLogs() {
        const agentCode = String(el.logAgent?.value || "").trim();
        if (!agentCode) {
            renderLogs([]);
            return;
        }
        const limit = Number(el.logLimit?.value || 50);
        const params = new URLSearchParams({ agent_code: agentCode, limit: String(limit) });
        const data = await getJson(urls.events + `?${params.toString()}`);
        const rows = Array.isArray(data.events) ? data.events : [];
        renderLogs(rows);
    }

    async function refreshAll() {
        await Promise.all([refreshAgents(), refreshJobs(), refreshReleases(), refreshLogs()]);
    }

    function handleCommandTypeChange() {
        const type = el.commandType.value;
        el.processWrap.style.display = type === "run_sap_process" ? "" : "none";
    }

    async function onDispatchSubmit(e) {
        e.preventDefault();
        const commandType = el.commandType.value;
        const body = {
            command_type: commandType,
            target_agent_code: el.agentCode.value || "",
            priority: Number(el.priority.value || 100),
            payload: {},
            requested_by: "panel",
        };

        const commandText = String(el.command.value || "").trim();
        if (commandText) {
            body.payload.command = commandText;
        }

        if (commandType === "run_sap_process") {
            const processId = Number(el.processId.value || 0);
            if (!processId) {
                showToast("SAP süreç seçmelisin", "error");
                return;
            }
            body.sap_process_id = processId;
        }

        const note = String(el.note.value || "").trim();
        if (note) {
            body.payload.note = note;
        }

        const submitBtn = el.form.querySelector("button[type='submit']");
        submitBtn.disabled = true;
        try {
            const data = await postJson(urls.dispatch, body);
            showToast(`İş kuyruğa eklendi (#${data.job.job_id})`, "success");
            el.note.value = "";
            await refreshAll();
        } catch (err) {
            showToast("İş gönderme hatası: " + err.message, "error");
        } finally {
            submitBtn.disabled = false;
        }
    }

    async function onAgentSubmit(e) {
        e.preventDefault();
        const body = {
            code: String(el.agentNewCode?.value || "").trim(),
            name: String(el.agentNewName?.value || "").trim(),
            token: String(el.agentNewToken?.value || "").trim(),
            is_enabled: String(el.agentEnabled?.value || "1") === "1",
            desired_version: String(el.agentDesired?.value || "").trim(),
        };
        if (!body.code || !body.name || !body.token) {
            showToast("Ajan kodu, adı ve token zorunlu", "error");
            return;
        }
        const btn = el.agentForm.querySelector("button[type='submit']");
        btn.disabled = true;
        try {
            const data = await postJson(urls.upsert, body);
            showToast(data.created ? "Ajan oluşturuldu" : "Ajan güncellendi", "success");
            el.agentNewToken.value = "";
            await refreshAll();
        } catch (err) {
            showToast("Ajan kaydetme hatası: " + err.message, "error");
        } finally {
            btn.disabled = false;
        }
    }

    async function onReleaseSubmit(e) {
        e.preventDefault();
        const version = String(el.releaseVersion?.value || "").trim();
        if (!version) {
            showToast("Version zorunlu", "error");
            return;
        }
        const formData = new FormData();
        formData.append("version", version);
        formData.append("download_url", String(el.releaseUrl?.value || "").trim());
        formData.append("checksum_sha256", String(el.releaseSha?.value || "").trim());
        formData.append("release_notes", String(el.releaseNotes?.value || "").trim());
        formData.append("install_command", String(el.releaseInstallCmd?.value || "").trim());
        formData.append("is_active", String(el.releaseActive?.value || "1") === "1" ? "1" : "0");
        formData.append("is_mandatory", String(el.releaseMandatory?.value || "0") === "1" ? "1" : "0");
        formData.append("created_by", "panel");
        const file = el.releaseFile?.files?.[0];
        if (file) {
            formData.append("setup_file", file);
        }
        const btn = el.releaseForm.querySelector("button[type='submit']");
        btn.disabled = true;
        try {
            await postForm(urls.releaseSave, formData);
            showToast("Release kaydedildi", "success");
            if (el.releaseFile) el.releaseFile.value = "";
            await refreshReleases();
        } catch (err) {
            showToast("Release kaydetme hatası: " + err.message, "error");
        } finally {
            btn.disabled = false;
        }
    }

    async function onSetDesiredVersion() {
        const version = String(el.desiredVersion?.value || "").trim();
        const agentCode = String(el.desiredAgent?.value || "").trim();
        if (!version) {
            showToast("Önce release seç", "error");
            return;
        }
        el.setDesiredBtn.disabled = true;
        try {
            await postJson(urls.setDesired, { version: version, agent_code: agentCode });
            showToast("Desired version atandı", "success");
            await refreshAgents();
        } catch (err) {
            showToast("Desired version hatası: " + err.message, "error");
        } finally {
            el.setDesiredBtn.disabled = false;
        }
    }

    async function onDeployRelease() {
        const version = String(el.deployVersion?.value || "").trim();
        const scope = String(el.deployScope?.value || "outdated").trim();
        const agent = String(el.deployAgent?.value || "").trim();
        if (!version) {
            showToast("Deploy için version seç", "error");
            return;
        }
        const body = {
            version: version,
            scope: scope,
            requested_by: "panel",
            agent_codes: scope === "single" && agent ? [agent] : [],
        };
        if (scope === "single" && !agent) {
            showToast("Single dağıtım için ajan seç", "error");
            return;
        }
        if (!confirm(`Release ${version} için deploy başlatılsın mı?`)) return;
        el.deployBtn.disabled = true;
        try {
            const data = await postJson(urls.releaseDeploy, body);
            showToast(`Deploy işleri üretildi: ${data.jobs_created}`, "success");
            await refreshAll();
        } catch (err) {
            showToast("Deploy hatası: " + err.message, "error");
        } finally {
            el.deployBtn.disabled = false;
        }
    }

    async function onBuildSetupExe() {
        const version = String(el.buildVersion?.value || "").trim();
        const forceRebuild = String(el.buildForce?.value || "0") === "1";
        if (!version) {
            showToast("Build için version gir", "error");
            return;
        }
        if (el.buildResult) {
            el.buildResult.textContent = "setup.exe build başlatıldı, lütfen bekleyin...";
        }
        el.buildBtn.disabled = true;
        try {
            const data = await postJson(urls.releaseBuildSetup, {
                version: version,
                force_rebuild: forceRebuild,
            });
            const link = String(data.download_url || "").trim();
            if (el.buildResult) {
                el.buildResult.innerHTML = link
                    ? `Hazır: <a href="${esc(link)}">setup.exe indir</a> (version: ${esc(data.version || version)})`
                    : `Build tamamlandı (version: ${esc(data.version || version)})`;
            }
            if (el.releaseVersion) el.releaseVersion.value = String(data.version || version);
            if (el.releaseUrl && link) el.releaseUrl.value = link;
            showToast(data.message || "setup.exe hazır", "success");
            await refreshReleases();
        } catch (err) {
            if (el.buildResult) {
                el.buildResult.textContent = "Build hatası: " + err.message;
            }
            showToast("Build hatası: " + err.message, "error");
        } finally {
            el.buildBtn.disabled = false;
        }
    }

    async function onBuildInstallPackage() {
        const version = String(el.packageVersion?.value || "").trim();
        const forceRebuild = String(el.packageForce?.value || "0") === "1";
        if (!version) {
            showToast("Paket için version gir", "error");
            return;
        }
        if (el.packageResult) {
            el.packageResult.textContent = "Kurumsal paket hazırlanıyor, lütfen bekleyin...";
        }
        el.packageBtn.disabled = true;
        try {
            const data = await postJson(urls.releaseBuildPackage, {
                version: version,
                force_rebuild: forceRebuild,
            });
            const link = String(data.package_url || "").trim();
            if (el.packageResult) {
                el.packageResult.innerHTML = link
                    ? `Hazır: <a href="${esc(link)}">kurumsal-paket.zip indir</a> (version: ${esc(data.version || version)})`
                    : `Paket tamamlandı (version: ${esc(data.version || version)})`;
            }
            if (el.releaseVersion) el.releaseVersion.value = String(data.version || version);
            if (el.releaseUrl && link) el.releaseUrl.value = link;
            showToast(data.message || "Kurumsal paket hazır", "success");
            await refreshReleases();
        } catch (err) {
            if (el.packageResult) {
                el.packageResult.textContent = "Paket hatası: " + err.message;
            }
            showToast("Paket hatası: " + err.message, "error");
        } finally {
            el.packageBtn.disabled = false;
        }
    }

    function init() {
        renderAgentOptions();
        renderProcessOptions();
        renderReleases(state.releases);
        handleCommandTypeChange();

        el.commandType.addEventListener("change", handleCommandTypeChange);
        el.form.addEventListener("submit", onDispatchSubmit);
        if (el.agentForm) el.agentForm.addEventListener("submit", onAgentSubmit);
        if (el.releaseForm) el.releaseForm.addEventListener("submit", onReleaseSubmit);
        if (el.setDesiredBtn) el.setDesiredBtn.addEventListener("click", onSetDesiredVersion);
        if (el.deployBtn) el.deployBtn.addEventListener("click", onDeployRelease);
        if (el.buildBtn) el.buildBtn.addEventListener("click", onBuildSetupExe);
        if (el.packageBtn) el.packageBtn.addEventListener("click", onBuildInstallPackage);
        if (el.logRefresh) el.logRefresh.addEventListener("click", () => refreshLogs().catch((err) => showToast(err.message, "error")));
        if (el.logAgent) el.logAgent.addEventListener("change", () => refreshLogs().catch((err) => showToast(err.message, "error")));
        if (el.logLimit) el.logLimit.addEventListener("change", () => refreshLogs().catch((err) => showToast(err.message, "error")));
        el.refreshBtn.addEventListener("click", () => refreshAll().catch((err) => showToast(err.message, "error")));
        el.limit.addEventListener("change", () => refreshJobs().catch((err) => showToast(err.message, "error")));
        if (el.jobStatus) el.jobStatus.addEventListener("change", () => refreshJobs().catch((err) => showToast(err.message, "error")));
        if (el.jobAgentFilter) el.jobAgentFilter.addEventListener("change", () => refreshJobs().catch((err) => showToast(err.message, "error")));
        if (el.jobSearch) {
            let timer = null;
            el.jobSearch.addEventListener("input", () => {
                if (timer) window.clearTimeout(timer);
                timer = window.setTimeout(() => refreshJobs().catch((err) => showToast(err.message, "error")), 300);
            });
        }

        refreshAll().catch((err) => showToast("Yükleme hatası: " + err.message, "error"));

        state.refreshTimer = window.setInterval(() => {
            refreshAll().catch(() => {});
        }, 15000);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
