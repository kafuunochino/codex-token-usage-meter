import AppKit
import Foundation

private struct LaunchOptions {
    let scriptPath: String
    let pythonPath: String

    static func parse() -> LaunchOptions {
        let args = CommandLine.arguments
        var script: String?
        var python: String?
        var index = 1
        while index < args.count {
            switch args[index] {
            case "--script" where index + 1 < args.count:
                script = args[index + 1]
                index += 2
            case "--python" where index + 1 < args.count:
                python = args[index + 1]
                index += 2
            default:
                index += 1
            }
        }

        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let pluginRoot = executable
            .deletingLastPathComponent() // MacOS
            .deletingLastPathComponent() // Contents
            .deletingLastPathComponent() // app bundle
            .deletingLastPathComponent() // assets
        let developmentScript = pluginRoot
            .appendingPathComponent("skills/token-usage/scripts/token_usage.py").path
        let bundledScript = Bundle.main
            .url(forResource: "token_usage", withExtension: "py")?.path
        return LaunchOptions(
            scriptPath: script ?? bundledScript ?? developmentScript,
            pythonPath: python ?? "/usr/bin/python3"
        )
    }
}

private final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

private enum WidgetLanguage: String {
    case english = "en"
    case chinese = "zh-Hans"
}

private let supportedRefreshIntervals = [1, 5, 10, 30, 60]

private final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let options = LaunchOptions.parse()
    private var panel: FloatingPanel!
    private var timer: Timer?
    private var refreshInFlight = false
    private var language: WidgetLanguage = .english
    private var refreshInterval = 5
    private var lastRefreshDate: Date?
    private var lastModelName: String?
    private var lastErrorMessage: String?
    private var settingsPopover: NSPopover?
    private weak var languageSettingLabel: NSTextField?
    private weak var refreshSettingLabel: NSTextField?
    private weak var languagePopup: NSPopUpButton?
    private weak var refreshPopup: NSPopUpButton?

    private let titleLabel = NSTextField(labelWithString: "Codex Usage")
    private let modelLabel = NSTextField(labelWithString: "Connecting to Codex…")
    private let inputCaption = NSTextField(labelWithString: "Input")
    private let cachedCaption = NSTextField(labelWithString: "Cached / hit")
    private let outputCaption = NSTextField(labelWithString: "Output")
    private let totalCaption = NSTextField(labelWithString: "Total")
    private let costCaption = NSTextField(labelWithString: "Budget Used (USD)")
    private let inputValue = NSTextField(labelWithString: "—")
    private let cachedValue = NSTextField(labelWithString: "—")
    private let outputValue = NSTextField(labelWithString: "—")
    private let totalValue = NSTextField(labelWithString: "—")
    private let costValue = NSTextField(labelWithString: "—")
    private let footerLabel = NSTextField(labelWithString: "Local metadata · refreshes every 5s")
    private let statusDot = NSTextField(labelWithString: "●")
    private let settingsButton = NSButton()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        loadPreferences()
        buildPanel()
        applyLocalization()
        restoreOrPlacePanel()
        panel.orderFrontRegardless()
        refresh()
        scheduleRefreshTimer()
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func windowDidMove(_ notification: Notification) {
        let origin = panel.frame.origin
        UserDefaults.standard.set(Double(origin.x), forKey: "panelX")
        UserDefaults.standard.set(Double(origin.y), forKey: "panelY")
    }

    private func buildPanel() {
        panel = FloatingPanel(
            contentRect: NSRect(x: 0, y: 0, width: 336, height: 236),
            styleMask: [.titled, .closable, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.delegate = self
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.title = "Codex Usage"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.standardWindowButton(.zoomButton)?.isHidden = true

        let blur = NSVisualEffectView()
        blur.material = .hudWindow
        blur.blendingMode = .behindWindow
        blur.state = .active
        blur.wantsLayer = true
        blur.layer?.cornerRadius = 18
        blur.layer?.masksToBounds = true
        panel.contentView = blur

        titleLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        titleLabel.textColor = .secondaryLabelColor

        statusDot.font = .systemFont(ofSize: 10, weight: .bold)
        statusDot.textColor = .systemOrange

        settingsButton.target = self
        settingsButton.action = #selector(showSettings(_:))
        settingsButton.isBordered = false
        settingsButton.imagePosition = .imageOnly
        settingsButton.contentTintColor = .secondaryLabelColor
        if let image = NSImage(systemSymbolName: "gearshape", accessibilityDescription: "Settings") {
            settingsButton.image = image
        } else {
            settingsButton.title = "⚙"
            settingsButton.font = .systemFont(ofSize: 14, weight: .regular)
        }

        let nativeCloseControlSpace = NSView()
        let headerSpacer = NSView()
        let header = NSStackView(views: [nativeCloseControlSpace, statusDot, titleLabel, headerSpacer, settingsButton])
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 7
        nativeCloseControlSpace.translatesAutoresizingMaskIntoConstraints = false
        settingsButton.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            nativeCloseControlSpace.widthAnchor.constraint(equalToConstant: 22),
            settingsButton.widthAnchor.constraint(equalToConstant: 22),
            settingsButton.heightAnchor.constraint(equalToConstant: 22),
        ])

        modelLabel.font = .systemFont(ofSize: 11, weight: .medium)
        modelLabel.textColor = .tertiaryLabelColor
        modelLabel.lineBreakMode = .byTruncatingTail

        configureValue(inputValue)
        configureValue(cachedValue)
        configureValue(outputValue)
        configureValue(totalValue)
        configureValue(costValue, emphasized: true)

        [inputCaption, cachedCaption, outputCaption, totalCaption, costCaption].forEach(configureCaption)

        let grid = NSGridView(views: [
            [inputCaption, inputValue],
            [cachedCaption, cachedValue],
            [outputCaption, outputValue],
            [totalCaption, totalValue],
            [costCaption, costValue],
        ])
        grid.rowSpacing = 7
        grid.columnSpacing = 18
        grid.column(at: 0).xPlacement = .leading
        grid.column(at: 1).xPlacement = .trailing

        footerLabel.font = .systemFont(ofSize: 10, weight: .regular)
        footerLabel.textColor = .tertiaryLabelColor
        footerLabel.lineBreakMode = .byTruncatingTail

        let stack = NSStackView(views: [header, modelLabel, grid, footerLabel])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false
        blur.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: blur.leadingAnchor, constant: 18),
            stack.trailingAnchor.constraint(equalTo: blur.trailingAnchor, constant: -18),
            stack.topAnchor.constraint(equalTo: blur.topAnchor, constant: 13),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: blur.bottomAnchor, constant: -12),
            header.widthAnchor.constraint(equalTo: stack.widthAnchor),
            modelLabel.widthAnchor.constraint(equalTo: stack.widthAnchor),
            grid.widthAnchor.constraint(equalTo: stack.widthAnchor),
            footerLabel.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])
    }

    private func configureCaption(_ label: NSTextField) {
        label.font = .systemFont(ofSize: 12, weight: .regular)
        label.textColor = .secondaryLabelColor
    }

    private func configureValue(_ label: NSTextField, emphasized: Bool = false) {
        label.font = emphasized
            ? .monospacedDigitSystemFont(ofSize: 18, weight: .bold)
            : .monospacedDigitSystemFont(ofSize: 13, weight: .semibold)
        label.textColor = emphasized ? .systemGreen : .labelColor
        label.alignment = .right
        label.setContentCompressionResistancePriority(.required, for: .horizontal)
    }

    private func restoreOrPlacePanel() {
        let defaults = UserDefaults.standard
        let screen = NSScreen.main ?? NSScreen.screens.first
        guard let visible = screen?.visibleFrame else { return }

        if defaults.object(forKey: "panelX") != nil,
           defaults.object(forKey: "panelY") != nil {
            let x = CGFloat(defaults.double(forKey: "panelX"))
            let y = CGFloat(defaults.double(forKey: "panelY"))
            let clampedX = min(max(x, visible.minX), visible.maxX - panel.frame.width)
            let clampedY = min(max(y, visible.minY), visible.maxY - panel.frame.height)
            panel.setFrameOrigin(NSPoint(x: clampedX, y: clampedY))
        } else {
            panel.setFrameOrigin(NSPoint(x: visible.minX + 18, y: visible.minY + 18))
        }
    }

    @objc private func showSettings(_ sender: NSButton) {
        if settingsPopover?.isShown == true {
            settingsPopover?.close()
            return
        }

        let languageLabel = NSTextField(labelWithString: "")
        let refreshLabel = NSTextField(labelWithString: "")
        [languageLabel, refreshLabel].forEach { label in
            label.font = .systemFont(ofSize: 12, weight: .medium)
            label.textColor = .secondaryLabelColor
        }

        let languageControl = NSPopUpButton(frame: .zero, pullsDown: false)
        languageControl.target = self
        languageControl.action = #selector(languageChanged(_:))
        let refreshControl = NSPopUpButton(frame: .zero, pullsDown: false)
        refreshControl.target = self
        refreshControl.action = #selector(refreshIntervalChanged(_:))

        let grid = NSGridView(views: [
            [languageLabel, languageControl],
            [refreshLabel, refreshControl],
        ])
        grid.translatesAutoresizingMaskIntoConstraints = false
        grid.rowSpacing = 12
        grid.columnSpacing = 18
        grid.column(at: 0).xPlacement = .leading
        grid.column(at: 1).xPlacement = .fill

        let contentView = NSView(frame: NSRect(x: 0, y: 0, width: 250, height: 108))
        contentView.addSubview(grid)
        NSLayoutConstraint.activate([
            grid.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16),
            grid.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16),
            grid.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 16),
            grid.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -16),
            languageControl.widthAnchor.constraint(greaterThanOrEqualToConstant: 118),
            refreshControl.widthAnchor.constraint(greaterThanOrEqualToConstant: 118),
        ])

        let controller = NSViewController()
        controller.view = contentView
        let popover = NSPopover()
        popover.behavior = .transient
        popover.contentSize = contentView.frame.size
        popover.contentViewController = controller
        settingsPopover = popover
        languageSettingLabel = languageLabel
        refreshSettingLabel = refreshLabel
        languagePopup = languageControl
        refreshPopup = refreshControl
        updateSettingsControls()
        popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
    }

    @objc private func languageChanged(_ sender: NSPopUpButton) {
        guard let selected = sender.selectedItem?.representedObject as? String,
              let selectedLanguage = WidgetLanguage(rawValue: selected)
        else { return }
        language = selectedLanguage
        UserDefaults.standard.set(language.rawValue, forKey: "widgetLanguage")
        applyLocalization()
        updateSettingsControls()
    }

    @objc private func refreshIntervalChanged(_ sender: NSPopUpButton) {
        guard let number = sender.selectedItem?.representedObject as? NSNumber else { return }
        let seconds = number.intValue
        guard supportedRefreshIntervals.contains(seconds) else { return }
        refreshInterval = seconds
        UserDefaults.standard.set(seconds, forKey: "refreshIntervalSeconds")
        scheduleRefreshTimer()
        updateFooter()
        refresh()
    }

    private func loadPreferences() {
        let defaults = UserDefaults.standard
        if let storedLanguage = defaults.string(forKey: "widgetLanguage"),
           let selectedLanguage = WidgetLanguage(rawValue: storedLanguage) {
            language = selectedLanguage
        } else {
            language = .english
        }

        let storedInterval = defaults.integer(forKey: "refreshIntervalSeconds")
        refreshInterval = supportedRefreshIntervals.contains(storedInterval) ? storedInterval : 5
    }

    private func scheduleRefreshTimer() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: TimeInterval(refreshInterval), repeats: true) { [weak self] _ in
            self?.refresh()
        }
        timer?.tolerance = min(0.25, TimeInterval(refreshInterval) * 0.1)
    }

    private func applyLocalization() {
        titleLabel.stringValue = "Codex Usage"
        inputCaption.stringValue = localized("Input", "输入")
        cachedCaption.stringValue = localized("Cached / hit", "缓存 / 命中率")
        outputCaption.stringValue = localized("Output", "输出")
        totalCaption.stringValue = localized("Total", "总计")
        costCaption.stringValue = localized("Budget Used (USD)", "预算消耗（美元）")
        settingsButton.toolTip = localized("Settings", "设置")
        panel.standardWindowButton(.closeButton)?.toolTip = localized("Close widget", "关闭小组件")
        updateModelLabel()
        updateFooter()
    }

    private func updateSettingsControls() {
        languageSettingLabel?.stringValue = localized("Language", "语言")
        refreshSettingLabel?.stringValue = localized("Refresh", "刷新时间")

        if let languagePopup {
            languagePopup.removeAllItems()
            [("English", WidgetLanguage.english), ("中文", WidgetLanguage.chinese)].forEach { title, value in
                languagePopup.addItem(withTitle: title)
                languagePopup.lastItem?.representedObject = value.rawValue
            }
            if let index = languagePopup.itemArray.firstIndex(where: {
                ($0.representedObject as? String) == language.rawValue
            }) {
                languagePopup.selectItem(at: index)
            }
        }

        if let refreshPopup {
            refreshPopup.removeAllItems()
            supportedRefreshIntervals.forEach { seconds in
                refreshPopup.addItem(withTitle: refreshIntervalTitle(seconds))
                refreshPopup.lastItem?.representedObject = NSNumber(value: seconds)
            }
            if let index = refreshPopup.itemArray.firstIndex(where: {
                ($0.representedObject as? NSNumber)?.intValue == refreshInterval
            }) {
                refreshPopup.selectItem(at: index)
            }
        }
    }

    private func localized(_ english: String, _ chinese: String) -> String {
        language == .chinese ? chinese : english
    }

    private func refreshIntervalTitle(_ seconds: Int) -> String {
        if language == .chinese {
            return "\(seconds) 秒"
        }
        return seconds == 1 ? "1 second" : "\(seconds) seconds"
    }

    private func refresh() {
        guard !refreshInFlight else { return }
        refreshInFlight = true

        let launchOptions = options
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: launchOptions.pythonPath)
            process.arguments = [launchOptions.scriptPath, "--scope", "all", "--widget-json"]
            process.standardOutput = output
            process.standardError = output

            do {
                try process.run()
            } catch {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.refreshInFlight = false
                    self.applyError(error.localizedDescription)
                }
                return
            }

            // Drain the pipe while the process is still running. Waiting for
            // termination first can deadlock once the report exceeds the
            // fixed macOS pipe buffer.
            let outputData = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            DispatchQueue.main.async {
                guard let self else { return }
                self.refreshInFlight = false
                if process.terminationStatus == 0 {
                    self.applySnapshot(outputData)
                } else {
                    let message = String(data: outputData, encoding: .utf8) ?? "Unable to read usage"
                    self.applyError(message)
                }
            }
        }
    }

    private func applySnapshot(_ data: Data) {
        guard
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let tokens = json["tokens"] as? [String: Any],
            let estimate = json["estimate"] as? [String: Any]
        else {
            applyError("Invalid usage response")
            return
        }

        let input = integer(tokens["input_tokens"])
        let cached = integer(tokens["cached_input_tokens"])
        let output = integer(tokens["output_tokens"])
        let total = integer(tokens["total_tokens"])
        let hitRate = decimal(tokens["cache_hit_rate_percent"])
        let usd = decimal(estimate["known_usd"])
        let fullyPriced = estimate["fully_priced"] as? Bool ?? false

        inputValue.stringValue = formatInteger(input)
        cachedValue.stringValue = "\(formatInteger(cached))  ·  \(String(format: "%.1f%%", hitRate))"
        outputValue.stringValue = formatInteger(output)
        totalValue.stringValue = formatInteger(total)
        costValue.stringValue = fullyPriced ? "≈ \(formatMoney(usd))" : "≥ \(formatMoney(usd))"
        inputValue.toolTip = NumberFormatter.widgetInteger.string(from: NSNumber(value: input))
        cachedValue.toolTip = NumberFormatter.widgetInteger.string(from: NSNumber(value: cached))
        outputValue.toolTip = NumberFormatter.widgetInteger.string(from: NSNumber(value: output))
        totalValue.toolTip = NumberFormatter.widgetInteger.string(from: NSNumber(value: total))

        lastModelName = nil
        if let models = json["models"] as? [[String: Any]], models.count == 1, let first = models.first {
            lastModelName = displayModel(first["model"] as? String ?? "unknown")
        }
        lastErrorMessage = nil
        lastRefreshDate = Date()
        updateModelLabel()
        statusDot.textColor = .systemGreen
        updateFooter()
    }

    private func applyError(_ message: String) {
        statusDot.textColor = .systemRed
        lastErrorMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        updateModelLabel()
        updateFooter()
    }

    private func updateModelLabel() {
        if lastErrorMessage != nil {
            modelLabel.stringValue = localized("Waiting for Codex usage data", "正在等待 Codex 用量数据")
            return
        }
        guard lastRefreshDate != nil else {
            modelLabel.stringValue = localized("Connecting to Codex…", "正在连接 Codex…")
            return
        }

        let prefix = localized("ALL CODEX", "全部 CODEX")
        let live = localized("LIVE", "实时")
        if let lastModelName {
            modelLabel.stringValue = "\(prefix)  ·  \(lastModelName)  ·  \(live)"
        } else {
            modelLabel.stringValue = "\(prefix)  ·  \(live)"
        }
    }

    private func updateFooter() {
        if let lastErrorMessage {
            footerLabel.stringValue = lastErrorMessage
            return
        }
        guard let lastRefreshDate else {
            footerLabel.stringValue = localized(
                "Local metadata · refreshes every \(refreshInterval)s",
                "本地元数据 · 每 \(refreshInterval) 秒刷新"
            )
            return
        }

        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        if language == .chinese {
            formatter.locale = Locale(identifier: "zh_CN")
            formatter.dateFormat = "yyyy年M月d日 EEEE HH:mm:ss"
        } else {
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = "yyyy-MM-dd EEEE HH:mm:ss"
        }
        let dateText = formatter.string(from: lastRefreshDate)
        footerLabel.stringValue = localized(
            "Refreshed at \(dateText)  ·  \(refreshInterval)s",
            "刷新于 \(dateText)  ·  \(refreshInterval) 秒"
        )
    }

    private func integer(_ value: Any?) -> Int64 {
        if let number = value as? NSNumber { return number.int64Value }
        return 0
    }

    private func decimal(_ value: Any?) -> Double {
        if let number = value as? NSNumber { return number.doubleValue }
        return 0
    }

    private func formatInteger(_ value: Int64) -> String {
        let magnitude = Double(value)
        let unit: (divisor: Double, suffix: String)?
        if magnitude >= 1_000_000_000 {
            unit = (1_000_000_000, "B")
        } else if magnitude >= 1_000_000 {
            unit = (1_000_000, "M")
        } else if magnitude >= 10_000 {
            unit = (10_000, "W")
        } else if magnitude >= 1_000 {
            unit = (1_000, "K")
        } else {
            unit = nil
        }
        guard let unit else {
            return NumberFormatter.widgetInteger.string(from: NSNumber(value: value)) ?? String(value)
        }
        let scaled = magnitude / unit.divisor
        let number = NumberFormatter.widgetCompact.string(from: NSNumber(value: scaled)) ?? String(format: "%.2f", scaled)
        return "\(number)\(unit.suffix)"
    }

    private func formatMoney(_ value: Double) -> String {
        let number = NumberFormatter.widgetMoney.string(from: NSNumber(value: value)) ?? String(format: "%.4f", value)
        return "$\(number)"
    }

    private func displayModel(_ model: String) -> String {
        let names = [
            "gpt-5.6-sol": "GPT-5.6 SOL",
            "gpt-5.6-terra": "GPT-5.6 TERRA",
            "gpt-5.6-luna": "GPT-5.6 LUNA",
            "gpt-5.5": "GPT-5.5",
            "gpt-5.4": "GPT-5.4",
            "gpt-5.4-mini": "GPT-5.4 MINI",
            "gpt-5.3-codex": "GPT-5.3 CODEX",
        ]
        return names[model] ?? model.uppercased()
    }
}

private extension NumberFormatter {
    static let widgetInteger: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter
    }()

    static let widgetCompact: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = false
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    static let widgetMoney: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = true
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 4
        return formatter
    }()
}

private let application = NSApplication.shared
private let delegate = AppDelegate()
application.delegate = delegate
application.run()
