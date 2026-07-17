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

private final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let options = LaunchOptions.parse()
    private var panel: FloatingPanel!
    private var timer: Timer?
    private var refreshInFlight = false

    private let modelLabel = NSTextField(labelWithString: "Connecting to Codex…")
    private let inputValue = NSTextField(labelWithString: "—")
    private let cachedValue = NSTextField(labelWithString: "—")
    private let outputValue = NSTextField(labelWithString: "—")
    private let totalValue = NSTextField(labelWithString: "—")
    private let costValue = NSTextField(labelWithString: "—")
    private let footerLabel = NSTextField(labelWithString: "Local metadata · refreshes every 5s")
    private let statusDot = NSTextField(labelWithString: "●")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        buildPanel()
        restoreOrPlacePanel()
        panel.orderFrontRegardless()
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
    }

    func windowDidMove(_ notification: Notification) {
        let origin = panel.frame.origin
        UserDefaults.standard.set(Double(origin.x), forKey: "panelX")
        UserDefaults.standard.set(Double(origin.y), forKey: "panelY")
    }

    private func buildPanel() {
        panel = FloatingPanel(
            contentRect: NSRect(x: 0, y: 0, width: 320, height: 250),
            styleMask: [.borderless, .nonactivatingPanel],
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
        panel.isMovableByWindowBackground = true
        panel.becomesKeyOnlyIfNeeded = true

        let blur = NSVisualEffectView()
        blur.material = .hudWindow
        blur.blendingMode = .behindWindow
        blur.state = .active
        blur.wantsLayer = true
        blur.layer?.cornerRadius = 18
        blur.layer?.masksToBounds = true
        panel.contentView = blur

        let title = NSTextField(labelWithString: "CODEX USAGE")
        title.font = .systemFont(ofSize: 12, weight: .semibold)
        title.textColor = .secondaryLabelColor

        statusDot.font = .systemFont(ofSize: 10, weight: .bold)
        statusDot.textColor = .systemOrange

        let closeButton = NSButton(title: "×", target: self, action: #selector(closeWidget))
        closeButton.isBordered = false
        closeButton.font = .systemFont(ofSize: 18, weight: .regular)
        closeButton.contentTintColor = .secondaryLabelColor
        closeButton.toolTip = "Close widget"

        let headerSpacer = NSView()
        let header = NSStackView(views: [statusDot, title, headerSpacer, closeButton])
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 7

        modelLabel.font = .systemFont(ofSize: 11, weight: .medium)
        modelLabel.textColor = .tertiaryLabelColor
        modelLabel.lineBreakMode = .byTruncatingTail

        configureValue(inputValue)
        configureValue(cachedValue)
        configureValue(outputValue)
        configureValue(totalValue)
        configureValue(costValue, emphasized: true)

        let grid = NSGridView(views: [
            [makeCaption("Input"), inputValue],
            [makeCaption("Cached / hit"), cachedValue],
            [makeCaption("Output"), outputValue],
            [makeCaption("Total"), totalValue],
            [makeCaption("Estimated USD"), costValue],
        ])
        grid.rowSpacing = 9
        grid.columnSpacing = 22
        grid.column(at: 0).xPlacement = .leading
        grid.column(at: 1).xPlacement = .trailing

        footerLabel.font = .systemFont(ofSize: 10, weight: .regular)
        footerLabel.textColor = .tertiaryLabelColor
        footerLabel.lineBreakMode = .byTruncatingTail

        let stack = NSStackView(views: [header, modelLabel, grid, footerLabel])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false
        blur.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: blur.leadingAnchor, constant: 18),
            stack.trailingAnchor.constraint(equalTo: blur.trailingAnchor, constant: -18),
            stack.topAnchor.constraint(equalTo: blur.topAnchor, constant: 15),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: blur.bottomAnchor, constant: -14),
            header.widthAnchor.constraint(equalTo: stack.widthAnchor),
            modelLabel.widthAnchor.constraint(equalTo: stack.widthAnchor),
            grid.widthAnchor.constraint(equalTo: stack.widthAnchor),
            footerLabel.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])
    }

    private func makeCaption(_ text: String) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .systemFont(ofSize: 12, weight: .regular)
        label.textColor = .secondaryLabelColor
        return label
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

    @objc private func closeWidget() {
        NSApp.terminate(nil)
    }

    private func refresh() {
        guard !refreshInFlight else { return }
        refreshInFlight = true

        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = URL(fileURLWithPath: options.pythonPath)
        process.arguments = [options.scriptPath, "--scope", "all", "--json"]
        process.standardOutput = stdout
        process.standardError = stderr

        process.terminationHandler = { [weak self] task in
            let outputData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errorData = stderr.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let self else { return }
                self.refreshInFlight = false
                if task.terminationStatus == 0 {
                    self.applySnapshot(outputData)
                } else {
                    let message = String(data: errorData, encoding: .utf8) ?? "Unable to read usage"
                    self.applyError(message)
                }
            }
        }

        do {
            try process.run()
        } catch {
            refreshInFlight = false
            applyError(error.localizedDescription)
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

        var modelText = "ALL CODEX  ·  LIVE"
        if let models = json["models"] as? [[String: Any]], models.count == 1, let first = models.first {
            let model = displayModel(first["model"] as? String ?? "unknown")
            modelText = "ALL CODEX  ·  \(model)  ·  LIVE"
        }
        modelLabel.stringValue = modelText
        statusDot.textColor = .systemGreen
        footerLabel.stringValue = "All local history  ·  \(DateFormatter.widgetTime.string(from: Date()))  ·  5s"
    }

    private func applyError(_ message: String) {
        statusDot.textColor = .systemRed
        modelLabel.stringValue = "Waiting for Codex usage data"
        footerLabel.stringValue = message.trimmingCharacters(in: .whitespacesAndNewlines)
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

private extension DateFormatter {
    static let widgetTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()
}

private let application = NSApplication.shared
private let delegate = AppDelegate()
application.delegate = delegate
application.run()
