// Appended to the unchanged production Rust implementation, before CXX transport.
mod ffi {
    unsafe extern "C" {
        fn mb_fft_sin(x: f64) -> f64;
        fn mb_fft_cos(x: f64) -> f64;
    }
    pub fn metabrowser_fft_sin(x: f64) -> f64 { unsafe { mb_fft_sin(x) } }
    pub fn metabrowser_fft_cos(x: f64) -> f64 { unsafe { mb_fft_cos(x) } }
}

fn component_reference(input: &[f32], k: usize) -> (f64, f64) {
    let mut real = 0.0; let mut imag = 0.0;
    for (i, &x) in input.iter().enumerate() {
        let angle = -2.0 * std::f64::consts::PI * (k * i) as f64 / input.len() as f64;
        real += x as f64 * ffi::metabrowser_fft_cos(angle);
        imag += x as f64 * ffi::metabrowser_fft_sin(angle);
    }
    (real, imag)
}

fn component_cache_checks() {
    let portable = get_fft(17, true); let native = get_fft(17, false);
    assert!(!Arc::ptr_eq(&portable.0, &native.0));
    assert!(Arc::ptr_eq(&portable.0, &get_fft(17, true).0));
    assert!(Arc::ptr_eq(&native.0, &get_fft(17, false).0));
    fn wrong(_: f64) -> (f64, f64) { (-77.0, 23.0) }
    rustfft::metabrowser_math::with_twiddle_provider(wrong, || {
        let mut fft = rustfft_new(11);
        let input: Vec<f32> = (0..11).map(|i| i as f32 / 13.0).collect();
        let mut real = vec![0.0; 6]; let mut imag = vec![0.0; 6];
        fft.do_fft(&input, &mut real, &mut imag);
        for k in 0..6 {
            let (r, im) = component_reference(&input, k);
            assert!((real[k] as f64 - r).abs() < 1e-5);
            assert!((imag[k] as f64 - im).abs() < 1e-5);
        }
        assert_eq!(rustfft::metabrowser_math::sin_cos(0.25), wrong(0.25));
    });
    assert!(!get_cache().read().unwrap().contains_key(&(509, true)));
    let barrier = Arc::new(std::sync::Barrier::new(8));
    let threads: Vec<_> = (0..8).map(|_| {
        let barrier = barrier.clone();
        std::thread::spawn(move || { barrier.wait(); get_fft(509, true) })
    }).collect();
    let plans: Vec<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
    assert!(plans.iter().all(|p| Arc::ptr_eq(&p.0, &plans[0].0)));
}

pub fn component_run() -> i32 {
    use std::io::Write;
    component_cache_checks();
    let mut sizes: Vec<usize> = (1..=15).map(|n| 1 << n).collect();
    sizes.extend([3, 5, 7, 15, 31, 257, 4097]);
    let mut out = std::io::BufWriter::new(std::fs::File::create("fft-component.bin").unwrap());
    out.write_all(b"MBFFT001").unwrap();
    out.write_all(&((sizes.len() * 5) as u32).to_le_bytes()).unwrap();
    let mut maximum_error = 0.0f32;
    for size in sizes { for pattern in 0u32..5 {
        let mut input: Vec<f32> = (0..size).map(|i| match pattern {
            0 => ((i * 17 % 257) as f32 - 128.0) / 137.0,
            1 => if i == 0 { 1.0 } else { 0.0 },
            2 => if i % 2 == 0 { 1.0 } else { -1.0 },
            3 => 0.25,
            _ => 0.0,
        }).collect();
        if pattern == 4 { input[size / 3] = 0.5; input[size / 7] = -0.25; }
        let packed = size.div_ceil(2);
        let mut real = vec![0.0; packed]; let mut imag = vec![0.0; packed];
        let mut restored = vec![0.0; size];
        let mut fft = rustfft_new_portable(size);
        fft.do_fft(&input, &mut real, &mut imag);
        fft.do_inverse_fft(&real, &imag, &mut restored);
        assert!(real.iter().chain(imag.iter()).chain(restored.iter()).all(|x| x.is_finite()));
        let error = input.iter().zip(restored.iter()).map(|(a,b)| (a-b).abs()).fold(0.0f32,f32::max);
        assert!(error <= 2e-5, "roundtrip size={size} pattern={pattern} error={error}");
        maximum_error = maximum_error.max(error);
        if size <= 32 {
            for k in 0..packed {
                let (r, i) = component_reference(&input, k);
                let expected_imag = if k==0 && size%2==0 { component_reference(&input,size/2).0 } else { i };
                assert!((real[k] as f64-r).abs() <= size as f64 * 2e-6);
                assert!((imag[k] as f64-expected_imag).abs() <= size as f64 * 2e-6);
            }
        }
        for x in [size as u32,pattern,packed as u32] {out.write_all(&x.to_le_bytes()).unwrap();}
        for data in [&input,&real,&imag,&restored] {
            for x in data { out.write_all(&x.to_bits().to_le_bytes()).unwrap(); }
        }
        out.write_all(&error.to_bits().to_le_bytes()).unwrap();
    }}
    out.flush().unwrap();
    println!("component cases=110 cache_isolation=pass concurrent_cold_planning=pass max_roundtrip_error={maximum_error}");
    0
}
