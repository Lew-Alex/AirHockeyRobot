import AVFoundation
import SwiftUI

/// One capture format of the back camera that can run at 60 fps or more.
struct CaptureFormatOption: Identifiable, Hashable {
    /// Index into `AVCaptureDevice.formats`.
    let id: Int
    let width: Int
    let height: Int
    let maxFPS: Double
    let binned: Bool

    var title: String {
        "\(width)x\(height), up to \(Int(maxFPS)) fps" + (binned ? " (binned)" : "")
    }
}

/// Runs the back camera at a chosen frame rate with a fixed shutter speed and
/// reports the frame rate that is actually delivered.
///
/// All camera work happens on `sessionQueue`. Frame statistics are gathered on
/// `frameQueue`. Published values are only ever changed on the main queue.
final class CameraController: NSObject, ObservableObject {

    static let fpsChoices = [60, 120, 240]
    static let shutterChoices = [120, 250, 500, 1000, 2000, 4000]

    // MARK: Published state

    @Published private(set) var message = "Starting camera..."
    @Published private(set) var cameraAvailable = true
    @Published private(set) var formatOptions: [CaptureFormatOption] = []
    @Published private(set) var activeFormatTitle = "-"
    @Published private(set) var targetFPS = 120
    @Published private(set) var shutterDenominator = 500
    @Published private(set) var iso: Float = 800
    @Published private(set) var isoRange: ClosedRange<Float> = 25...3200
    @Published private(set) var measuredFPS = 0.0
    @Published private(set) var maxGapMs = 0.0
    @Published private(set) var droppedFrames = 0
    @Published private(set) var appliedShutter = "-"
    @Published private(set) var appliedISO: Float = 0

    // MARK: Camera objects

    let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "camera120.session")
    private let frameQueue = DispatchQueue(label: "camera120.frames", qos: .userInteractive)
    private let videoOutput = AVCaptureVideoDataOutput()
    private var device: AVCaptureDevice?
    private var configured = false

    // Requested settings. Only touched on sessionQueue.
    private var requestedFormatIndex = -1
    private var requestedFPS = 120
    private var requestedShutter = 500
    private var requestedISO: Float = 800

    // Frame statistics. Only touched on frameQueue.
    private var windowStartPTS = 0.0
    private var windowFrames = 0
    private var lastPTS = 0.0
    private var windowMaxGapMs = 0.0
    private var droppedCount = 0

    // MARK: Public controls

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            sessionQueue.async { self.configureAndRun() }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                if granted {
                    self.sessionQueue.async { self.configureAndRun() }
                } else {
                    self.publishMessage("Camera access was denied. Allow it in Settings.")
                }
            }
        default:
            publishMessage("Camera access is off. Allow it in Settings.")
        }
    }

    func stop() {
        sessionQueue.async {
            if self.session.isRunning {
                self.session.stopRunning()
            }
        }
    }

    func selectFormat(id: Int) {
        sessionQueue.async {
            self.requestedFormatIndex = id
            self.applyFormatAndFrameRate()
            self.applyExposure()
        }
    }

    func setTargetFPS(_ fps: Int) {
        sessionQueue.async {
            self.requestedFPS = fps
            self.applyFormatAndFrameRate()
            self.applyExposure()
        }
    }

    func setShutter(denominator: Int) {
        sessionQueue.async {
            self.requestedShutter = denominator
            self.applyExposure()
        }
    }

    func setISO(_ value: Float) {
        sessionQueue.async {
            self.requestedISO = value
            self.applyExposure()
        }
    }

    // MARK: Session setup (sessionQueue)

    private func configureAndRun() {
        if !configured {
            guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                publish {
                    self.cameraAvailable = false
                    self.message = "No camera found. The iOS Simulator has none, so run this on an iPhone."
                }
                return
            }
            device = camera
            guard buildSession(with: camera) else { return }

            let options = Self.availableFormats(for: camera)
            requestedFormatIndex = Self.defaultFormatID(in: options, fps: requestedFPS)
            publish { self.formatOptions = options }
            configured = true
        }

        applyFormatAndFrameRate()
        applyExposure()
        if !session.isRunning {
            session.startRunning()
        }
    }

    private func buildSession(with camera: AVCaptureDevice) -> Bool {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        session.sessionPreset = .inputPriority

        do {
            let input = try AVCaptureDeviceInput(device: camera)
            guard session.canAddInput(input) else {
                publishMessage("Could not add the camera input.")
                return false
            }
            session.addInput(input)
        } catch {
            publishMessage("Camera input error: \(error.localizedDescription)")
            return false
        }

        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        ]
        videoOutput.setSampleBufferDelegate(self, queue: frameQueue)
        guard session.canAddOutput(videoOutput) else {
            publishMessage("Could not add the video output.")
            return false
        }
        session.addOutput(videoOutput)

        // Stabilization crops and delays the image, so keep it off.
        if let connection = videoOutput.connection(with: .video), connection.isVideoStabilizationSupported {
            connection.preferredVideoStabilizationMode = .off
        }
        return true
    }

    // MARK: Format and exposure (sessionQueue)

    /// Formats worth offering: video-range 4:2:0 that can reach at least 60 fps.
    private static func availableFormats(for camera: AVCaptureDevice) -> [CaptureFormatOption] {
        var result: [CaptureFormatOption] = []
        for (index, format) in camera.formats.enumerated() {
            let maxFPS = format.videoSupportedFrameRateRanges.map { $0.maxFrameRate }.max() ?? 0
            guard maxFPS >= 60 else { continue }
            let subtype = CMFormatDescriptionGetMediaSubType(format.formatDescription)
            guard subtype == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange else { continue }
            let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            result.append(CaptureFormatOption(
                id: index,
                width: Int(dimensions.width),
                height: Int(dimensions.height),
                maxFPS: maxFPS,
                binned: format.isVideoBinned
            ))
        }
        return result.sorted {
            if $0.width * $0.height != $1.width * $1.height {
                return $0.width * $0.height < $1.width * $1.height
            }
            return $0.maxFPS < $1.maxFPS
        }
    }

    /// The smallest format that reaches `fps`, else the fastest one available.
    private static func defaultFormatID(in options: [CaptureFormatOption], fps: Int) -> Int {
        let fastEnough = options.filter { $0.maxFPS >= Double(fps) }
        if let smallest = fastEnough.min(by: { $0.width * $0.height < $1.width * $1.height }) {
            return smallest.id
        }
        return options.max(by: { $0.maxFPS < $1.maxFPS })?.id ?? -1
    }

    private func applyFormatAndFrameRate() {
        guard let camera = device,
              requestedFormatIndex >= 0,
              requestedFormatIndex < camera.formats.count else { return }
        let format = camera.formats[requestedFormatIndex]

        // The requested rate must lie inside one of the format's supported ranges.
        let ranges = format.videoSupportedFrameRateRanges
        var fps = Double(requestedFPS)
        if !ranges.contains(where: { $0.minFrameRate <= fps && fps <= $0.maxFrameRate }) {
            fps = ranges.map { $0.maxFrameRate }.max() ?? 30
        }
        let frameDuration = CMTime(value: 1, timescale: CMTimeScale(fps.rounded()))

        do {
            try camera.lockForConfiguration()
        } catch {
            publishMessage("Could not lock the camera: \(error.localizedDescription)")
            return
        }
        defer { camera.unlockForConfiguration() }

        camera.activeFormat = format
        camera.activeVideoMinFrameDuration = frameDuration
        camera.activeVideoMaxFrameDuration = frameDuration

        // Fixed focus and white balance keep the picture steady for tracking.
        if camera.isFocusModeSupported(.locked) {
            camera.focusMode = .locked
        }
        if camera.isWhiteBalanceModeSupported(.locked) {
            camera.whiteBalanceMode = .locked
        }

        let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
        let title = "\(dimensions.width)x\(dimensions.height)" + (format.isVideoBinned ? " binned" : "")
        let appliedFPS = Int(fps.rounded())
        publish {
            self.activeFormatTitle = title
            self.targetFPS = appliedFPS
        }

        frameQueue.async {
            self.droppedCount = 0
            self.windowFrames = 0
            self.windowMaxGapMs = 0
        }
    }

    /// Sets a fixed shutter speed and ISO inside what the active format allows.
    private func applyExposure() {
        guard let camera = device else { return }
        let format = camera.activeFormat

        var duration = CMTime(value: 1, timescale: CMTimeScale(requestedShutter))
        if CMTimeCompare(duration, format.minExposureDuration) < 0 {
            duration = format.minExposureDuration
        }
        if CMTimeCompare(duration, format.maxExposureDuration) > 0 {
            duration = format.maxExposureDuration
        }
        // An exposure cannot be longer than one frame.
        if CMTimeCompare(duration, camera.activeVideoMinFrameDuration) > 0 {
            duration = camera.activeVideoMinFrameDuration
        }
        let clampedISO = min(max(requestedISO, format.minISO), format.maxISO)

        do {
            try camera.lockForConfiguration()
        } catch {
            publishMessage("Could not lock the camera: \(error.localizedDescription)")
            return
        }
        camera.setExposureModeCustom(duration: duration, iso: clampedISO, completionHandler: nil)
        camera.unlockForConfiguration()

        let range = format.minISO...max(format.maxISO, format.minISO + 1)
        let shutter = requestedShutter
        publish {
            self.shutterDenominator = shutter
            self.iso = clampedISO
            self.isoRange = range
            self.message = "Camera running. Shutter and ISO are fixed."
        }
    }

    // MARK: Publishing helpers

    private func publish(_ update: @escaping () -> Void) {
        DispatchQueue.main.async(execute: update)
    }

    private func publishMessage(_ text: String) {
        publish { self.message = text }
    }

    private static func shutterText(_ exposureSeconds: Double) -> String {
        guard exposureSeconds > 0 else { return "-" }
        return "1/\(Int((1.0 / exposureSeconds).rounded()))"
    }
}

// MARK: - Frame statistics

extension CameraController: AVCaptureVideoDataOutputSampleBufferDelegate {

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds

        if lastPTS > 0 {
            windowMaxGapMs = max(windowMaxGapMs, (pts - lastPTS) * 1000)
        }
        lastPTS = pts

        if windowFrames == 0 {
            windowStartPTS = pts
        }
        windowFrames += 1

        let elapsed = pts - windowStartPTS
        guard elapsed >= 1.0 else { return }

        let fps = Double(windowFrames - 1) / elapsed
        let gap = windowMaxGapMs
        let drops = droppedCount
        let exposure = device?.exposureDuration.seconds ?? 0
        let isoNow = device?.iso ?? 0
        windowFrames = 0
        windowMaxGapMs = 0

        publish {
            self.measuredFPS = fps
            self.maxGapMs = gap
            self.droppedFrames = drops
            self.appliedShutter = Self.shutterText(exposure)
            self.appliedISO = isoNow
        }
    }

    func captureOutput(_ output: AVCaptureOutput,
                       didDrop sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        droppedCount += 1
    }
}
