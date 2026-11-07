import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var camera = CameraController()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(session: camera.session)
                .ignoresSafeArea()

            VStack(alignment: .leading) {
                StatsView(camera: camera)
                Spacer()
                ControlsView(camera: camera)
            }
            .padding()
        }
        .onAppear {
            camera.start()
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            camera.stop()
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }
}

/// Live numbers: what the camera was asked for and what it actually delivers.
struct StatsView: View {
    @ObservedObject var camera: CameraController

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(camera.message)
            Text("format  \(camera.activeFormatTitle)")
            Text("fps     \(String(format: "%.1f", camera.measuredFPS)) measured, \(camera.targetFPS) target")
            Text("gap     \(String(format: "%.1f", camera.maxGapMs)) ms max, \(camera.droppedFrames) dropped")
            Text("shutter \(camera.appliedShutter) applied, 1/\(camera.shutterDenominator) asked   ISO \(Int(camera.appliedISO))")
        }
        .font(.system(.footnote, design: .monospaced))
        .foregroundColor(.white)
        .padding(8)
        .background(Color.black.opacity(0.6))
        .cornerRadius(8)
    }
}

struct ControlsView: View {
    @ObservedObject var camera: CameraController

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text("fps").foregroundColor(.white)
                ForEach(CameraController.fpsChoices, id: \.self) { fps in
                    ChoiceChip(title: "\(fps)", selected: camera.targetFPS == fps) {
                        camera.setTargetFPS(fps)
                    }
                }
                Menu {
                    ForEach(camera.formatOptions) { option in
                        Button(option.title) { camera.selectFormat(id: option.id) }
                    }
                } label: {
                    Text("Format: \(camera.activeFormatTitle)")
                        .font(.footnote.monospaced())
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(Color.black.opacity(0.6))
                        .foregroundColor(.white)
                        .cornerRadius(8)
                }
            }

            HStack(spacing: 6) {
                Text("shutter").foregroundColor(.white)
                ForEach(CameraController.shutterChoices, id: \.self) { denominator in
                    ChoiceChip(title: "1/\(denominator)", selected: camera.shutterDenominator == denominator) {
                        camera.setShutter(denominator: denominator)
                    }
                }
            }

            HStack {
                Text("ISO").foregroundColor(.white)
                Slider(
                    value: Binding(
                        get: { Double(camera.iso) },
                        set: { camera.setISO(Float($0)) }
                    ),
                    in: Double(camera.isoRange.lowerBound)...Double(camera.isoRange.upperBound)
                )
                Text("\(Int(camera.iso))")
                    .font(.footnote.monospaced())
                    .foregroundColor(.white)
                    .frame(width: 50, alignment: .trailing)
            }
        }
        .padding(8)
        .background(Color.black.opacity(0.6))
        .cornerRadius(8)
    }
}

/// A small tappable option that is highlighted when selected.
struct ChoiceChip: View {
    let title: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.footnote.monospaced())
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(selected ? Color.yellow : Color.white.opacity(0.2))
                .foregroundColor(selected ? .black : .white)
                .cornerRadius(8)
        }
    }
}
