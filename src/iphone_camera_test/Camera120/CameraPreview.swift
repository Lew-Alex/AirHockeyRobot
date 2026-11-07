import AVFoundation
import SwiftUI
import UIKit

/// A UIView whose layer is the camera preview.
final class PreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        // layerClass guarantees this cast.
        layer as! AVCaptureVideoPreviewLayer
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(sessionDidStart),
            name: .AVCaptureSessionDidStartRunning,
            object: nil
        )
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not used")
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    @objc private func sessionDidStart() {
        DispatchQueue.main.async { self.applyOrientation() }
    }

    /// The preview connection only exists once the session has an input, so
    /// the orientation is set when the session starts. The app is locked to
    /// landscape (home indicator on the right).
    func applyOrientation() {
        if let connection = previewLayer.connection, connection.isVideoOrientationSupported {
            connection.videoOrientation = .landscapeRight
        }
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspect
        view.applyOrientation()
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.applyOrientation()
    }
}
