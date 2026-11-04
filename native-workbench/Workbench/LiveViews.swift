import SwiftUI
import WorkbenchCore

/// Connected-repository workspace. Explicit Accept & build actions share
/// their viewport with observed source changes. Saved viewing stays read-only.
struct LiveWorkbenchView: View {
    var live: LiveWorkbenchModel
    @State private var operationsExpanded = false
    @State private var savedSourceMode = "Source"

    var body: some View {
        @Bindable var live = live
        ScrollViewReader { proxy in
        List {
            Section {
                Text("A privacy analyst queues a customer's records package to fulfill a CCPA access request. Their internal access is revoked before they can download it.")
                Text("When should access be checked: at request-time, just after the incoming records request is successfully received and processed, or at delivery-time, when the records are retrieved and published to the customer?")
                    .font(.headline)
                    .accessibilityIdentifier("live-question")
                Text("Shared constraints: tenant isolation · authorized enqueue · audit before release · audit failure blocks release.")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("The question") }

            Section {
                if live.isConnected {
                    DisclosureGroup {
                        LabeledContent("Resolved commit", value: String((live.repoCommit ?? "").prefix(12)))
                            .font(.body.monospaced())
                        if let sid = live.sessionID {
                            LabeledContent("Session", value: sid)
                                .font(.caption.monospaced())
                                .accessibilityIdentifier("live-session")
                        }
                    } label: {
                        Text("Connected · \(live.repoCanonical ?? "repository")")
                            .accessibilityIdentifier("live-connection-toggle")
                    }
                } else {
                    Button("Connect and import") { Task { await live.connect() } }
                        .buttonStyle(.borderedProminent)
                        .tint(Color.trajectoryTeal)
                        .accessibilityIdentifier("live-connect")
                        .disabled(live.busy)
                    TextField("Saved session ID", text: $live.resumeSessionID)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.body.monospaced())
                        .accessibilityIdentifier("live-resume-id")
                    Button("Resume session") { Task { await live.resume() } }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("live-resume")
                        .disabled(live.busy)
                }
                Text(live.statusLine).font(.callout)
                    .accessibilityIdentifier("live-status")
            } header: { Text("Repository") }

            Section {
                LabeledContent("Accepted rule", value: live.state.acceptedTitle)
                    .accessibilityIdentifier("live-accepted-rule")
                Text(live.constructionParentLine)
                    .font(.caption.monospaced())
                    .accessibilityIdentifier("live-construction-parent")
                Text("Select a branch to explore it. Accepted marks the rule currently in force.")
                    .font(.callout).foregroundStyle(.secondary)
                LiveDecisionFork(live: live)
                LiveHistoryPreview(live: live)
                DisclosureGroup("Change intent without building") {
                    Button("Accept selected answer") { Task { await live.accept() } }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("live-accept")
                        .disabled(!live.isConnected || !live.state.isAcceptEnabled || live.busy)
                    Text("Accept changes the owner rule only.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let error = live.lastError {
                    Text(error).foregroundStyle(.red)
                        .accessibilityIdentifier("live-failure")
                }
                if let action = live.lastNextAction {
                    Text(action).font(.callout).foregroundStyle(.secondary)
                        .accessibilityIdentifier("live-next-action")
                }
            } header: { Text("Your choice → source") } footer: {
                Text("Accept & build records your rule, then constructs a new candidate. Viewing saved work changes neither the rule nor its source. Checks, commits, pushes, and CI are separate actions.")
            }

            if let job = live.constructionJob, let construction = job.construction {
                Section {
                    LiveConstructionPanel(live: live, job: job, construction: construction)
                        .id(job.jobID)
                        .id("live-construction")
                } header: { Text("Construction · \(construction.candidate)") }
            }

            if let record = live.state.candidates[live.state.viewed] {
                Section {
                    Text(live.state.contextLine).font(.caption)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("live-source-context")
                    HStack {
                        Button("View check evidence") {
                            withAnimation { proxy.scrollTo("evidence-anchor", anchor: .top) }
                        }
                        .accessibilityIdentifier("live-jump-evidence")
                        Button("View decision history") {
                            withAnimation { proxy.scrollTo("history-anchor", anchor: .top) }
                        }
                        .accessibilityIdentifier("live-jump-history")
                    }.buttonStyle(.bordered)
                    Picker("File", selection: $live.sourcePath) {
                        Text("worker.go").tag("queued/worker.go")
                        Text("queue.go").tag("queued/queue.go")
                        Text("tests").tag("queued/queued_test.go")
                        Text("intent").tag(".trajectory/intent.json")
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("live-source-picker")
                    .onChange(of: live.sourcePath) { _, _ in
                        Task { await live.loadSource() }
                    }
                    Text("Path: \(live.sourcePath)").font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("live-source-path")
                    Picker("Show", selection: $savedSourceMode) {
                        Text("Source").tag("Source")
                        Text("Changes").tag("Changes")
                    }.pickerStyle(.segmented)
                    if savedSourceMode == "Source" {
                        if live.sourceLoadedFor == "\(live.state.viewed)|\(live.sourcePath)" {
                            Text("Showing \(live.sourceLoadedFor)").font(.caption)
                                .accessibilityIdentifier("live-source-meta")
                            LiveCodeText(text: live.sourceText)
                                .accessibilityIdentifier("live-source-text")
                        } else {
                            Text("Load this saved file to inspect its bytes.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                    } else if live.diffLoadedFor == live.state.viewed {
                        Text("Diff for candidate \(live.diffLoadedFor) · all changed files")
                            .font(.caption).accessibilityIdentifier("live-diff-meta")
                        LiveDiffText(text: live.diffText)
                            .accessibilityIdentifier("live-diff-text")
                    }
                    HStack {
                        Button("Load source") { Task { await live.loadSource() } }
                            .accessibilityIdentifier("live-load-source")
                        Button("Load diff vs parent") {
                            savedSourceMode = "Changes"
                            Task { await live.loadDiff() }
                        }
                        .accessibilityIdentifier("live-load-diff")
                    }.buttonStyle(.bordered)
                    DisclosureGroup("Saved source identity") {
                        LabeledContent("Candidate", value: record.name)
                        Text("Tree \(record.tree)").font(.caption.monospaced())
                        if let parent = record.parentCandidate {
                            Text("Parent candidate \(parent)")
                        }
                        if let tree = record.parentTree {
                            Text("Parent tree \(tree)").font(.caption.monospaced())
                        }
                        Text("Git base \(record.sourceParent)").font(.caption.monospaced())
                        if let generator = record.generator {
                            if let provider = generator.provider, let model = generator.model {
                                LabeledContent("Model", value: "\(provider) · \(model)")
                                    .font(.caption).accessibilityIdentifier("live-saved-provider")
                            }
                            if let id = generator.sessionID {
                                Text("Agent session \(id)").font(.caption.monospaced())
                            }
                            if let code = generator.exitCode {
                                LabeledContent("Generator exit", value: String(code))
                            }
                        }
                    }
                } header: { Text("Saved source · \(record.name)") } footer: {
                    Text("Read-only source and changes from this candidate's retained bytes.")
                }
            }

            if live.state.candidates[live.state.viewed] != nil {
            Section {
                Text(live.state.contextLine).font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("live-view-context")
                    .id("evidence-anchor")
                Button("View decision history") {
                    withAnimation { proxy.scrollTo("history-anchor", anchor: .top) }
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("live-evidence-jump-history")
                if live.activeJob?.construction != nil {
                    Text("These results belong to saved \(live.state.viewed). The running construction has no check result.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let name = live.returnCandidateName {
                    Button("Return to \(name)") {
                        Task { await live.viewSavedCandidate(name) }
                    }
                    .buttonStyle(.borderedProminent).tint(Color.trajectoryTeal)
                    .accessibilityIdentifier("live-return-\(name)")
                    Text("Latest retained candidate matching the accepted rule.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let consequence = live.state.viewedConsequence {
                    Text(consequence).accessibilityIdentifier("live-consequence")
                }
                Label(live.state.binding.title,
                      systemImage: live.state.binding == .current ? "checkmark.circle" : "clock.arrow.circlepath")
                    .font(.headline).foregroundStyle(Color.trajectoryTeal)
                    .accessibilityLabel("Applicability: \(live.state.binding.title).")
                Text(live.outcomeLine).accessibilityIdentifier("live-outcome")
                if let excerpt = live.guardExcerpt {
                    Text("Decisive guard · \(live.sourceLoadedFor)")
                        .font(.caption).foregroundStyle(.secondary)
                    LiveCodeText(text: excerpt).accessibilityIdentifier("live-guard-excerpt")
                }
                if let commit = live.state.candidates[live.state.viewed]?.commit {
                    LabeledContent("Commit", value: String(commit.prefix(12)))
                        .font(.body.monospaced()).accessibilityIdentifier("live-commit-sha")
                    if let run = live.state.viewedRun {
                        LabeledContent("Run", value: "\(run.runID) · \(run.conclusion ?? "running")")
                            .accessibilityIdentifier("live-run-conclusion")
                        Text(run.url).font(.caption).foregroundStyle(.secondary)
                    } else {
                        Text("No exact-head run observed for this commit.").font(.caption)
                    }
                } else {
                    Text("Not committed.").font(.caption).foregroundStyle(.secondary)
                }
            } header: { Text("Saved \(live.state.viewed) · check and build evidence") }
            }

            Section {
                LabeledContent("Accepted intent", value: live.state.acceptedTitle)
                    .accessibilityIdentifier("live-map-accepted")
                    .id("history-anchor")
                ForEach(live.state.historyOrder, id: \.name) { node in
                    let name = node.name
                    if let record = live.state.candidates[name] {
                        let parent = live.state.parentCandidate(for: name)
                        let ancestry = parent.map { "parent Candidate \($0)" }
                            ?? record.parentCandidate.map { "recorded parent \($0), unresolved tree" }
                            ?? "baseline \(live.state.mapBaseline(for: name) ?? "unrecorded")"
                        let cursor = live.state.viewed == name ? "viewing" : "not viewed"
                        let relationship = record.answer == live.state.accepted
                            ? "matches accepted rule" : "different rule"
                        Button {
                            Task { await live.viewSavedCandidate(name) }
                        } label: {
                            LiveMapRow(record: record, parentName: parent,
                                       baseline: live.state.mapBaseline(for: name),
                                       matchesRule: record.answer == live.state.accepted,
                                       isViewed: live.state.viewed == name,
                                       check: live.state.checkSummary(for: name))
                                .padding(.leading, CGFloat(min(node.depth, 3)) * 12)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("live-map-\(name)")
                        .accessibilityLabel("Candidate \(name), \(record.answer.title), \(ancestry), \(cursor), \(relationship), \(live.state.checkSummary(for: name).title).")
                        .accessibilityHint("Views saved source only. Does not accept or construct.")
                    }
                }
            } header: { Text("Decision map") } footer: {
                Text("Each node keeps its recorded parent. Several candidates can match the accepted rule; viewing a node never accepts that artifact.")
            }

            Section {
                ForEach(live.state.historyOrder, id: \.name) { node in
                    let name = node.name
                    if let record = live.state.candidates[name] {
                        Button {
                            Task { await live.viewSavedCandidate(name) }
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("View saved \(name)")
                                Text("\(record.answer.shortTitle) · \(live.state.checkSummary(for: name).title) · tree \(record.tree.prefix(12))")
                                    .font(.caption).foregroundStyle(.secondary)
                            }.frame(minHeight: 44)
                        }
                        .accessibilityIdentifier("live-candidate-\(name)")
                    }
                }
                Text(live.countsLine).font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("live-counts")
            } header: { Text("Retained candidates") }

            Section {
                DisclosureGroup(isExpanded: $operationsExpanded) {
                    TextField("Candidate name", text: $live.candidateName)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .accessibilityIdentifier("live-candidate-name")
                        .disabled(live.busy)
                    LiveOpButton(title: "Check", id: "live-check", enabled: live.checkEnabled,
                                 succeeded: live.state.operationSucceeded(.check, for: live.candidateName),
                                 running: live.busy && live.activeOp == "check") {
                        Task { await live.check() }
                    }
                    TextField("Commit message", text: $live.commitMessage)
                        .accessibilityIdentifier("live-commit-message")
                        .disabled(live.busy)
                    LiveOpButton(title: "Commit", id: "live-commit", enabled: live.commitEnabled,
                                 succeeded: live.state.operationSucceeded(.commit, for: live.candidateName),
                                 running: live.busy && live.activeOp == "commit") {
                        Task { await live.commit() }
                    }
                    LiveOpButton(title: "Push", id: "live-push", enabled: live.pushEnabled,
                                 succeeded: live.state.operationSucceeded(.push, for: live.candidateName),
                                 running: live.busy && live.activeOp == "push") {
                        Task { await live.push() }
                    }
                    LiveOpButton(title: "Observe run", id: "live-observe", enabled: live.observeEnabled,
                                 succeeded: live.state.operationSucceeded(.observe, for: live.candidateName),
                                 running: live.busy && live.activeOp == "observe") {
                        Task { await live.observe() }
                    }
                    if let job = live.activeJob, !job.isTerminal {
                        LiveOpButton(title: "Cancel \(live.activeOp ?? job.op)", id: "live-cancel", enabled: true) {
                            Task { await live.cancelActive() }
                        }
                    }
                } label: {
                    Text("Further operations on \(live.candidateName)")
                        .accessibilityIdentifier("live-operations-toggle")
                }
            } header: { Text("Explicit next actions") } footer: { Text("Check, commit, push, and observe remain separate. A completed construction is not a passing check.") }
        }
        .contentMargins(.bottom, 96, for: .scrollContent)
        .navigationTitle("Live Workbench")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: live.constructionJob?.jobID) { previous, current in
            guard let current, current != previous else { return }
            // Reveal a newly submitted run once. Polls update the same
            // source in place and never fight the user's reading cursor.
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo("live-construction", anchor: .top)
            }
        }
        }
    }
}

/// The two timing rules share a visible decision point. Selecting a branch
/// is a preview cursor; only its explicit build action accepts the rule.
private struct LiveDecisionFork: View {
    var live: LiveWorkbenchModel

    var body: some View {
        VStack(spacing: 0) {
            Label("When is access checked?", systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                .accessibilityIdentifier("live-decision-fork")
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
            DecisionForkLines()
                .stroke(Color.secondary.opacity(0.6), lineWidth: 1.5)
                .frame(height: 28)
                .accessibilityHidden(true)
            HStack(alignment: .top, spacing: 8) {
                ForEach(LiveAnswer.allCases, id: \.self) { answer in
                    LiveDecisionBranch(live: live, answer: answer)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                }
            }
        }
    }
}

struct DecisionForkLines: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let mid = rect.midX
        path.move(to: CGPoint(x: mid, y: 0))
        path.addLine(to: CGPoint(x: mid, y: rect.midY))
        path.move(to: CGPoint(x: rect.width * 0.25, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.width * 0.25, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.width * 0.75, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.width * 0.75, y: rect.maxY))
        return path
    }
}

private struct LiveDecisionBranch: View {
    var live: LiveWorkbenchModel
    var answer: LiveAnswer

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { live.select(answer) } label: {
                VStack(alignment: .leading, spacing: 5) {
                    Text(answer.shortTitle).font(.headline)
                    Text(answer == .queueTime
                         ? "Just after the request is received and processed."
                         : "When the records are retrieved and delivered.")
                        .font(.caption).foregroundStyle(.secondary)
                    if live.state.selected == answer {
                        Label("Selected", systemImage: "circle.dashed")
                            .font(.caption).foregroundStyle(Color.accentColor)
                    }
                    if live.state.accepted == answer {
                        Label("Accepted", systemImage: "checkmark.circle.fill")
                            .font(.caption).foregroundStyle(Color.trajectoryTeal)
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .topLeading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("live-answer-\(answer.rawValue)")
            .accessibilityHint("Selects this branch to explore; it does not accept the rule.")
            Button {
                Task { await live.construct(answer) }
            } label: {
                Text("Accept & build \(live.nextCandidateName(for: answer))")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .tint(Color.trajectoryTeal)
            .disabled(!live.isConnected || live.busy)
            .accessibilityIdentifier("live-construct-\(answer.rawValue)")
            .accessibilityLabel("Accept and build \(live.nextCandidateName(for: answer)), \(answer.shortTitle)")
            .accessibilityHint("Accepts this rule and constructs a candidate from the displayed parent.")
        }
        .padding(10)
        .background(live.state.accepted == answer ? Color.trajectoryTeal.opacity(0.10) : Color.secondary.opacity(0.06),
                    in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(live.state.selected == answer ? Color.accentColor : Color.secondary.opacity(0.2),
                              lineWidth: live.state.selected == answer ? 2 : 1)
        }
    }
}

/// Only actual retained candidates and commits appear in this small tree.
private struct LiveHistoryPreview: View {
    var live: LiveWorkbenchModel

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("Your navigable history").font(.subheadline.weight(.semibold))
                .accessibilityIdentifier("live-history-preview")
            Text("Select highlights a branch. Accept & build records the rule and starts construction. Open a saved node to navigate; commits appear here when created.")
                .font(.caption).foregroundStyle(.secondary)
            Label("Starting source", systemImage: "circle")
                .font(.caption).foregroundStyle(.secondary)
            if live.state.candidates.isEmpty {
                Text("Saved candidates will appear here after construction.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(live.state.historyOrder, id: \.name) { node in
                    let name = node.name
                    if let record = live.state.candidates[name] {
                        Button {
                            Task { await live.viewSavedCandidate(name) }
                        } label: {
                            HStack(alignment: .top, spacing: 6) {
                                Image(systemName: "arrow.turn.down.right")
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("\(name) · \(record.answer.shortTitle)")
                                    Text(historyDetail(record))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if live.state.viewed == name {
                                    Text("Viewing").font(.caption)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .padding(.leading, 8 + CGFloat(min(node.depth, 3)) * 16)
                        .accessibilityIdentifier("live-saved-\(name)")
                        .accessibilityHint("View saved source without changing the accepted rule.")
                    }
                }
            }
        }
        .padding(.vertical, 6)
    }

    private func historyDetail(_ record: LiveCandidate) -> String {
        let parent = live.state.parentCandidate(for: record.name).map { "From \($0) · " } ?? ""
        let identity = record.commit.map { "Commit \(String($0.prefix(12)))" } ?? "Candidate · not committed"
        return parent + identity
    }
}

private struct LiveConstructionPanel: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    var live: LiveWorkbenchModel
    var job: LiveCompanionClient.Job
    var construction: LiveConstruction
    @State private var mode = "Changes"

    private var file: LiveConstructionFile? {
        construction.files.first { $0.path == live.constructionFilePath }
            ?? construction.files.first
    }

    private var isPolling: Bool {
        live.activeJob?.jobID == job.jobID && !job.isTerminal
    }

    private var narrative: String {
        switch construction.stage {
        case "queued":
            "You chose \(construction.answer.shortTitle.lowercased()). The build request is queued."
        case "preparing":
            "Preparing \(construction.candidate) from the pinned parent source."
        case "invoking":
            "Synthesizing \(construction.candidate) from your chosen rule."
        case "editing":
            "Updating \(construction.candidate). These are its observed saved files."
        case "validating":
            "The agent finished. The companion is checking the allowed source boundary."
        case "succeeded":
            "\(construction.candidate) is ready to inspect. \(construction.changedPaths.map { "\($0.count) changed files." } ?? "Source retained.") Construction did not run checks."
        case "failed", "cancelled":
            "Construction \(construction.stage). No candidate was published by this run."
        default:
            "Observed stage: \(construction.stage)."
        }
    }

    private func eventText(_ event: LiveConstructionEvent) -> String {
        switch event.kind {
        case "process_started": "Synthesis started."
        case "process_exited": "Synthesis finished. Checking source changes."
        default: event.message
        }
    }

    var body: some View {
        @Bindable var live = live
        VStack(alignment: .leading, spacing: 12) {
            Text("Your choice: \(construction.answer.shortTitle). \(narrative)").font(.callout)
                .accessibilityIdentifier("live-construction-narrative")
            LabeledContent("Accepted rule now", value: live.state.acceptedTitle)
                .font(.caption).accessibilityIdentifier("live-construction-accepted")
            LabeledContent("Generating with", value: "\(construction.provider) · \(construction.model)")
                .font(.caption).accessibilityIdentifier("live-construction-provider")
            if isPolling {
                HStack {
                    ProgressView()
                    Text(liveConstructionStageTitle(construction.stage)).font(.caption)
                    Spacer()
                    Button("Cancel build") { Task { await live.cancelActive() } }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("live-cancel-construction")
                }
            } else if !job.isTerminal {
                Text("Last observed stage; updates are currently unavailable.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let parent = construction.parentCandidate {
                Text("From saved \(parent) → \(construction.answer.shortTitle.lowercased()) rule")
                    .font(.caption)
            }
            if construction.provisional, !construction.files.isEmpty {
                Text("Observed working source · provisional until construction completes")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("live-provisional-source")
            }
            if let output = construction.outputTree, construction.hasPublishedCandidate {
                Text("Created tree \(output.prefix(12))")
                    .font(.caption.monospaced()).accessibilityIdentifier("live-construction-tree")
                if let paths = construction.changedPaths {
                    Text(paths.isEmpty ? "No files changed." : "Changed: \(paths.joined(separator: ", "))")
                        .font(.caption).accessibilityIdentifier("live-construction-changed-files")
                }
            }
            if !construction.files.isEmpty {
                HStack(alignment: .top, spacing: 16) {
                    if sizeClass == .regular {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Decision → source").font(.headline)
                            Text(construction.answer.title).font(.callout)
                            if let parent = construction.parentCandidate {
                                Label("Saved \(parent)", systemImage: "doc.text")
                            } else {
                                Label("Repository baseline", systemImage: "doc.text")
                            }
                            Image(systemName: "arrow.down").foregroundStyle(.secondary)
                            Label(construction.candidate, systemImage: "hammer")
                            Text(liveConstructionStageTitle(construction.stage)).font(.caption).foregroundStyle(.secondary)
                        }
                        .frame(width: 190, alignment: .leading)
                    }
                VStack(alignment: .leading, spacing: 8) {
                Picker("Changed file", selection: $live.constructionFilePath) {
                    ForEach(construction.files) { source in
                        Text(source.path.replacingOccurrences(of: "queued/", with: ""))
                            .tag(source.path)
                    }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("live-construction-file")
                Picker("Code view", selection: $mode) {
                    Text("Changes").tag("Changes")
                    Text("Source").tag("Source")
                    Text("Before").tag("Before")
                }.pickerStyle(.segmented)
                if let file {
                    Text(file.path).font(.caption.monospaced())
                    if mode == "Changes" {
                        if file.diff.isEmpty {
                            Text("No saved change observed in this file.")
                                .font(.callout).foregroundStyle(.secondary)
                            LiveCodeText(text: file.after)
                        } else {
                            LiveDiffText(text: file.diff)
                                .accessibilityIdentifier("live-construction-diff")
                        }
                    } else {
                        LiveCodeText(text: mode == "Before" ? file.before : file.after)
                            .accessibilityIdentifier("live-construction-source")
                    }
                }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else if isPolling {
                Text("Waiting for an observed source snapshot.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            if let error = construction.error ?? job.error {
                Text(error).font(.callout).foregroundStyle(.red)
            }
            ForEach(Array(construction.events.suffix(3))) { event in
                Text(eventText(event)).font(.caption).foregroundStyle(.secondary)
            }
            DisclosureGroup("Run details") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Job \(job.jobID)")
                    if let id = construction.generatorSessionID { Text("Agent session \(id)") }
                    if let revision = construction.intentRevision { Text("Intent revision \(revision)") }
                    if let parent = construction.parentTree { Text("Parent tree \(parent)") }
                    if let base = construction.sourceParent { Text("Git base \(base)") }
                    if let output = construction.outputTree { Text("Output tree \(output)") }
                    if let file { Text("\(file.path) SHA256 \(file.sha256)") }
                    ForEach(construction.events) { event in
                        Text("\(event.at) · \(eventText(event))")
                    }
                }.font(.caption.monospaced()).textSelection(.enabled)
            }
        }
    }
}

private struct LiveCodeText: View {
    var text: String
    var body: some View {
        ScrollView(.horizontal) {
            Text(verbatim: text)
                .font(.system(size: 12, design: .monospaced))
                .textSelection(.enabled)
                .padding(.vertical, 4)
        }
    }
}

private struct LiveDiffText: View {
    var text: String
    var body: some View {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { row in
                    Text(verbatim: row.element.isEmpty ? " " : row.element)
                        .foregroundStyle(color(for: row.element))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .font(.system(size: 12, design: .monospaced))
            .textSelection(.enabled)
            .padding(.vertical, 4)
    }

    private func color(for line: String) -> Color {
        if line.hasPrefix("+++") || line.hasPrefix("---") || line.hasPrefix("@@") { return .secondary }
        if line.hasPrefix("+") { return Color.trajectoryTeal }
        if line.hasPrefix("-") { return .red }
        return .primary
    }
}

private struct LiveOpButton: View {
    var title: String
    var id: String
    var enabled: Bool
    var succeeded = false
    var running = false
    var action: () -> Void

    private var completedTitle: String {
        switch title {
        case "Check": "Checked"
        case "Commit": "Committed"
        case "Push": "Pushed"
        case "Observe run": "Run verified"
        default: title
        }
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if succeeded { Image(systemName: "checkmark.circle.fill") }
                if running { ProgressView().controlSize(.small) }
                Text(succeeded ? completedTitle : title)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .foregroundStyle(succeeded ? Color(red: 0.08, green: 0.48, blue: 0.23) : (enabled ? Color.accentColor : Color.secondary))
            .background(succeeded ? Color.green.opacity(0.16) : Color.secondary.opacity(0.10),
                        in: Capsule())
            .overlay(Capsule().stroke(succeeded ? Color.green.opacity(0.5) : .clear))
        }
        .buttonStyle(LiveOperationButtonStyle())
        .accessibilityIdentifier(id)
        .accessibilityValue(succeeded ? "Completed successfully" : (running ? "In progress" : ""))
        .disabled(!enabled || succeeded || running)
    }
}

private struct LiveOperationButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.opacity(configuration.isPressed ? 0.8 : 1)
    }
}

private struct LiveMapRow: View {
    var record: LiveCandidate
    var parentName: String?
    var baseline: String?
    var matchesRule: Bool
    var isViewed: Bool
    var check: LiveCheckSummary
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if let parent = parentName {
                Label("Parent: \(parent)", systemImage: "arrow.down")
                    .font(.caption).foregroundStyle(.secondary)
                if let tree = record.parentTree {
                    Text("parent tree \(tree.prefix(12))").font(.caption.monospaced()).foregroundStyle(.secondary)
                }
            } else if let recorded = record.parentCandidate {
                Label("Recorded parent: \(recorded) · unresolved tree", systemImage: "questionmark.circle")
                    .font(.caption).foregroundStyle(.secondary)
                if let tree = record.parentTree {
                    Text("expected parent tree \(tree.prefix(12))")
                        .font(.caption.monospaced()).foregroundStyle(.secondary)
                }
            } else if let baseline {
                Label("baseline \(baseline)", systemImage: "arrow.down")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("live-map-baseline-\(record.name)")
            }
            Text("Candidate \(record.name) · \(record.answer.shortTitle)")
            HStack {
                if matchesRule {
                    Label("Matches accepted rule", systemImage: "circle")
                        .foregroundStyle(Color.trajectoryTeal)
                }
                if isViewed { Label("Viewing", systemImage: "eye") }
            }.font(.caption)
            Label(check.title, systemImage: check == .passed ? "checkmark.circle.fill" :
                    check == .failed ? "xmark.circle.fill" : "circle.dashed")
                .font(.caption.weight(.semibold))
                .foregroundStyle(check == .passed ? Color.green : check == .failed ? Color.red : Color.secondary)
            Text("tree \(record.tree.prefix(12))\(record.commit.map { " · \($0.prefix(12))" } ?? " · uncommitted")")
                .font(.caption.monospaced()).foregroundStyle(.secondary)
        }.padding(.vertical, 4)
    }
}

extension LiveWorkbenchModel {
    var busy: Bool { isSubmitting || activeJob.map { !$0.isTerminal } == true }

    func parentCandidate(for name: String) -> String? { state.parentCandidate(for: name) }

    var guardExcerpt: String? {
        let key = "\(state.viewed)|queued/worker.go"
        guard sourceLoadedFor == key, !sourceText.isEmpty else { return nil }
        return decisiveGuardExcerpt(sourceText: sourceText)
    }

    var generateEnabled: Bool {
        isConnected && !busy && state.accepted != nil
            && state.candidates[candidateName] == nil && !candidateName.isEmpty
    }

    var checkEnabled: Bool {
        guard isConnected, !busy, let record = state.candidates[candidateName] else { return false }
        return !state.operationSucceeded(.check, for: candidateName)
            && (record.status == "generated" || record.status == "check_failed")
    }

    var commitEnabled: Bool {
        isConnected && !busy && !state.operationSucceeded(.commit, for: candidateName)
            && state.candidates[candidateName]?.status == "checked"
    }

    var pushEnabled: Bool {
        isConnected && !busy && !state.operationSucceeded(.push, for: candidateName)
            && state.candidates[candidateName]?.commit != nil
    }

    var observeEnabled: Bool {
        isConnected && !busy && state.candidates[candidateName]?.commit != nil
            && !state.operationSucceeded(.observe, for: candidateName)
    }

    var countsLine: String {
        "\(state.candidates.count) candidates · \(state.verifications.count) verifications · \(state.commits.count) commits"
    }

    var outcomeLine: String {
        if let verified = state.viewedVerificationForTree {
            let result = verified.passed ? "passed" : "failed"
            let scenario = verified.scenarioStatus.map { " · scenario \($0)" } ?? ""
            let step = verified.failingStep.map { " at \($0)" } ?? ""
            return "Applicable check \(result)\(step)\(scenario). \(verified.testsPassed.count) named tests passed."
        }
        if state.verifications.contains(where: { $0.candidate == state.viewed }) {
            return "Earlier evidence exists but matches no current tree. It verifies nothing."
        }
        return "No verification for this candidate yet."
    }
}

// Owner-directed delivery is backed by the private host bridge. No provider
// credentials or fixture results are embedded in the iOS application.
private struct OwnerDeliveryState: Decodable {
    struct Job: Decodable {
        let status: String
        let auditCount: Int
        let exportCount: Int
        let accessAtDelivery: Bool?
        enum CodingKeys: String, CodingKey {
            case status, auditCount = "audit_count", exportCount = "export_count", accessAtDelivery = "access_at_delivery"
        }
    }
    struct Result: Decodable {
        struct Example: Decodable {
            struct Output: Decodable {
                let status: String?
                let events: [String]?
                var description: String {
                    let eventsText = events.map { $0.isEmpty ? "no events" : $0.joined(separator: " → ") } ?? "events unavailable"
                    return "\(status ?? "outcome unavailable"), \(eventsText)"
                }
            }
            let name: String
            let satisfied: Bool?
            let expected: Output?
            let observed: Output?
            enum CodingKeys: String, CodingKey { case name, satisfied, expected, observed }
            init(from decoder: Decoder) throws {
                let container = try decoder.container(keyedBy: CodingKeys.self)
                name = try container.decode(String.self, forKey: .name)
                satisfied = try? container.decode(Bool.self, forKey: .satisfied)
                expected = try? container.decode(Output.self, forKey: .expected)
                observed = try? container.decode(Output.self, forKey: .observed)
            }
        }
        let verdict: String
        let cases: [Example]?
    }
    struct Checks: Decodable {
        let baseline: Result
        let wrongFix: Result
        let candidate: Result
        let modelEventsSHA256: String?
        enum CodingKeys: String, CodingKey {
            case baseline, candidate, wrongFix = "wrong_fix"
            case modelEventsSHA256 = "model_events_sha256"
        }
        var permitsApplication: Bool {
            baseline.verdict == "violated" && wrongFix.verdict == "violated" && candidate.verdict == "satisfied"
        }
    }
    struct Application: Decodable { let state: String; let sha256: String? }
    struct Resolution: Decodable {
        let state: String
        let stage: String
        let reason: String?
    }
    struct Receipt: Decodable, Identifiable {
        struct Detail: Decodable {
            let jobID: String?
            let decision: String?
            let status: String?
            let reason: String?
            let error: String?
            let eventsSHA256: String?
            enum CodingKeys: String, CodingKey { case jobID = "job_id", eventsSHA256 = "events_sha256", decision, status, reason, error }
            var summary: String {
                [jobID.map { "Job \($0.prefix(8))" }, decision, status, reason, error]
                    .compactMap { $0 }.joined(separator: " · ")
            }
        }
        let id: Int
        let kind: String
        let detail: Detail
    }
    let report: String?
    let decision: String?
    let baseline: Job?
    let checks: Checks?
    let application: Application
    let replay: Job?
    let requestTimeReplay: Job?
    let resolution: Resolution?
    let recovery: Job?
    let source: String?
    let receipts: [Receipt]
    let readableReceipt: String?
    var synthesizedCurrent: Bool {
        guard let checks, checks.permitsApplication, let hash = checks.modelEventsSHA256,
              let generation = receipts.last(where: { ["generation_started", "generation_completed", "generation_failed"].contains($0.kind) }) else { return false }
        return generation.kind == "generation_completed" && generation.detail.eventsSHA256 == hash
    }
    enum CodingKeys: String, CodingKey {
        case report, decision, baseline, checks, application, replay, resolution, recovery, source, receipts
        case requestTimeReplay = "request_time_replay"
        case readableReceipt = "readable_receipt"
    }
}

struct OwnerDeliveryView: View {
    @State private var state: OwnerDeliveryState?
    @State private var report = "A customer received records after access was revoked."
    @State private var busy = false
    @State private var busyAction: String?
    @State private var error: String?
    @State private var detail = ""
    private let baseURL = URL(string: "http://127.0.0.1:8139")!

    var body: some View {
        List {
            Section("1 · Describe the problem") {
                TextField("What happened?", text: $report, axis: .vertical)
                    .disabled(state?.report != nil || busy)
                    .accessibilityIdentifier("owner-report")
                action("Start report", "report", fields: ["description": report], done: state?.report != nil, enabled: !report.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if state?.report != nil { Text(state?.report ?? "").font(.caption) }
            }
            Section("2 · Reproduce") {
                Text("Queue the records, revoke access, then attempt delivery.")
                action("Reproduce the issue", "reproduce", done: state?.baseline?.status == "exported", enabled: state?.report != nil)
                if let job = state?.baseline {
                    Label("Before: \(job.status) · \(job.exportCount) export", systemImage: "exclamationmark.triangle")
                        .accessibilityIdentifier("owner-baseline")
                }
            }
            Section("3 · Decide when access is checked") {
                Text("Request time is when the records request is received. Delivery time is when the records are released to the customer.")
                HStack(alignment: .top) {
                    VStack(alignment: .leading) {
                        Text("Request time").font(.headline)
                        Text("Honor authorization captured with the request").font(.caption)
                        action("Choose request time", "decide", fields: ["choice":"request-time"], done: state?.decision == "request-time", enabled: state?.baseline != nil && state?.decision == nil, identifier: "decide-request")
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading) {
                        Text("Delivery time").font(.headline)
                        Text("Block release if access was revoked").font(.caption)
                        action("Choose delivery time", "decide", fields: ["choice":"delivery-time"], done: state?.decision == "delivery-time", enabled: state?.baseline != nil && state?.decision == nil)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("Protected: an audit is saved before release.").font(.caption)
            }
            if state?.decision == "request-time" {
                Section("4 · Request-time outcome") {
                    if let replay = state?.requestTimeReplay, replay.status == "exported", replay.auditCount == 1, replay.exportCount == 1, replay.accessAtDelivery == false {
                        Text("For this observed case, the original authorized request remains valid after revocation. No source change was needed.")
                    } else {
                        Text("The request-time replay is not yet complete. No source change has been applied.")
                    }
                    if let replay = state?.requestTimeReplay {
                        Label("After: \(replay.status) · \(replay.auditCount) audit · \(replay.exportCount) export", systemImage: replay.status == "exported" && replay.auditCount == 1 && replay.exportCount == 1 && replay.accessAtDelivery == false ? "checkmark.shield" : "exclamationmark.triangle")
                            .accessibilityIdentifier("owner-request-replay")
                    }
                    if state?.requestTimeReplay == nil || state?.requestTimeReplay?.status == "interrupted" {
                        action("Resume request-time replay", "resume_request_time", done: false, enabled: true)
                    }
                }
            } else {
            Section("4 · Resolve within this decision") {
                Text("One synthesis attempt, then independent checks, private application, and replay.")
                action("Resolve delivery", "resolve", done: state?.resolution?.state == "completed" && state?.replay?.status == "access_revoked" && state?.replay?.exportCount == 0, enabled: state?.decision != nil && state?.application.state != "applied" && state?.resolution == nil)
                if let resolution = state?.resolution {
                    Text("\(resolution.state.capitalized) · \(resolution.stage)\(resolution.reason.map { " · \($0)" } ?? "")")
                        .font(.caption).accessibilityIdentifier("owner-resolution-status")
                    if resolution.state == "interrupted" ||
                        (resolution.state == "running" && ["checking", "application", "replay"].contains(resolution.stage)) ||
                        (resolution.state == "running" && resolution.stage == "synthesis" && state?.checks != nil) ||
                        (resolution.state == "failed" && resolution.stage == "application_or_replay") {
                        action("Resume delivery", "resume_resolution", done: false, enabled: true)
                    }
                }
            }
            Section("Inspect independent checks") {
                Text("Synthesize a candidate or check retained work against the original behavior and an authored wrong fix.")
                action("Synthesize & check", "synthesize", done: state?.synthesizedCurrent == true, enabled: state?.decision != nil && state?.application.state != "applied" && state?.resolution == nil)
                action("Check retained candidate", "check", done: state?.checks?.permitsApplication == true && state?.synthesizedCurrent != true, enabled: state?.decision != nil && state?.application.state != "applied" && state?.resolution == nil)
                if let checks = state?.checks {
                    LabeledContent("Original", value: checks.baseline.verdict)
                    LabeledContent("Authored wrong fix", value: checks.wrongFix.verdict)
                    if let example = checks.wrongFix.cases?.first(where: { $0.satisfied == false }) {
                        Text("\(example.name.capitalized) example: expected \(example.expected?.description ?? "unavailable"); observed \(example.observed?.description ?? "unavailable").")
                            .font(.caption).foregroundStyle(.secondary)
                            .accessibilityIdentifier("owner-wrong-fix-reason")
                    }
                    LabeledContent("Muse candidate", value: checks.candidate.verdict)
                        .accessibilityIdentifier("owner-candidate-verdict")
                    if let source = state?.source {
                        DisclosureGroup("Inspect candidate source") {
                            Text(source).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        }
                    }
                    Text(state?.synthesizedCurrent == true ? "The current candidate came from this synthesis attempt." : "The retained candidate was generated earlier.").font(.caption).foregroundStyle(.secondary)
                }
            }
            Section("5 · Apply and replay") {
                action("Apply checked source", "apply", done: state?.application.state == "applied", enabled: state?.checks?.permitsApplication == true)
                if let hash = state?.application.sha256 { Text("Source \(hash.prefix(12))").font(.caption.monospaced()) }
                action("Replay original request", "replay", done: state?.replay?.status == "access_revoked" && state?.replay?.exportCount == 0, enabled: state?.application.state == "applied")
                if let job = state?.replay {
                    Label("After: \(job.status) · \(job.exportCount) exports", systemImage: job.status == "access_revoked" && job.exportCount == 0 ? "checkmark.shield" : "exclamationmark.triangle")
                        .accessibilityIdentifier("owner-replay")
                }
            }
            Section("6 · Recovery") {
                Text("Interrupt an authorized delivery after its audit is saved, then recover it.")
                action("Simulate interruption", "interrupt", done: state?.recovery?.status == "interrupted" || state?.recovery?.status == "exported", enabled: state?.application.state == "applied")
                action("Recover delivery", "recover", done: state?.recovery?.status == "exported", enabled: state?.recovery?.status == "interrupted")
                if let job = state?.recovery {
                    Text("\(job.status) · \(job.auditCount) audit · \(job.exportCount) exports")
                        .accessibilityIdentifier("owner-recovery")
                }
            }
            }
            if let state {
                if let receipt = state.readableReceipt {
                    Section("Resolution receipt") {
                        DisclosureGroup("View receipt") {
                            Text(receipt)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                        }
                        ShareLink(item: receipt, subject: Text("Private resolution receipt")) {
                            Label("Share receipt", systemImage: "square.and.arrow.up")
                        }
                        .accessibilityIdentifier("owner-share-receipt")
                    }
                }
                Section("Resolution history") {
                    ForEach(state.receipts) { receipt in
                        VStack(alignment: .leading) {
                            Text(receipt.kind.replacingOccurrences(of: "_", with: " ")).font(.caption.weight(.semibold))
                            if !receipt.detail.summary.isEmpty {
                                Text(receipt.detail.summary).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            if let error { Section("Action needs attention") { Text(error).foregroundStyle(.red) } }
            if busy { ProgressView(["synthesize", "resolve"].contains(busyAction ?? "") ? "Synthesizing…" : "Working…") }
            if !detail.isEmpty { Text(detail).font(.caption).foregroundStyle(.secondary) }
        }
        .navigationTitle("Resolve an issue")
        .task { await refresh() }
    }

    @ViewBuilder private func action(_ title: String, _ op: String, fields: [String: String] = [:], done: Bool, enabled: Bool, identifier: String? = nil) -> some View {
        if done {
            Text("\(title) ✓")
                .frame(maxWidth: .infinity, minHeight: 42)
                .foregroundStyle(Color.white)
                .background(Color(red: 0.08, green: 0.48, blue: 0.25), in: RoundedRectangle(cornerRadius: 10))
                .accessibilityLabel("\(title), completed")
                .accessibilityIdentifier("owner-action-\(identifier ?? op)-completed")
        } else {
            Button {
                Task { await perform(op, fields: fields) }
            } label: {
                Text(title)
                    .frame(maxWidth: .infinity, minHeight: 42)
                    .foregroundStyle(enabled && !busy ? Color.white : Color.secondary)
                    .background(enabled && !busy ? Color.trajectoryTeal : Color.gray.opacity(0.18), in: RoundedRectangle(cornerRadius: 10))
            }
            .buttonStyle(.plain)
            .disabled(!enabled || busy)
            .accessibilityIdentifier("owner-action-\(identifier ?? op)")
        }
    }

    private func refresh() async {
        do {
            let (data, response) = try await URLSession.shared.data(from: baseURL.appendingPathComponent("state"))
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            state = try JSONDecoder().decode(OwnerDeliveryState.self, from: data)
            error = nil
        } catch {
            self.error = "Private companion unavailable. Start the owner-delivery bridge on this Mac."
        }
    }

    private func perform(_ action: String, fields: [String: String]) async {
        busy = true; busyAction = action; error = nil
        defer { busy = false; busyAction = nil }
        do {
            var body = fields; body["action"] = action
            var request = URLRequest(url: baseURL.appendingPathComponent("action"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
            request.timeoutInterval = ["synthesize", "resolve"].contains(action) ? 600 : 120
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
                let message = (try? JSONSerialization.jsonObject(with: data) as? [String: String])?["error"] ?? "Companion request failed"
                throw NSError(domain: "OwnerDelivery", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
            }
            state = try JSONDecoder().decode(OwnerDeliveryState.self, from: data)
            detail = "Saved by the private companion."
        } catch {
            let message = error.localizedDescription
            await refresh()
            self.error = message
        }
    }
}
