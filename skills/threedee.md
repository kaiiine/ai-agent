---
name: threedee
description: Builds and scaffolds Three.js scenes from scratch: React Three Fiber, GSAP, ScrollTrigger, 3D, WebGL, postprocessing. Use when writing new 3D web code.
aliases: [three, r3f, 3d]
---

━━ STACK : THREE.JS / REACT THREE FIBER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD :
    pnpm create vite@latest <nom> -- --template react-ts
    shell_cd("<nom>") && shell_run("pnpm install")
    shell_run("pnpm add three @react-three/fiber @react-three/drei @react-three/postprocessing")
    shell_run("pnpm add gsap @gsap/react lenis framer-motion")
    shell_run("pnpm add -D @types/three")
    → JAMAIS PNG + CSS transform pour simuler de la 3D. Toujours un vrai GLB ou géométrie R3F.

━━ RÈGLES R3F FONDAMENTALES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    • Canvas dans composant "use client" (Next.js) ou fichier client normal.
    • useFrame() pour toutes les animations — jamais requestAnimationFrame direct.
    • Géométries lourdes → useMemo(). Matériaux partagés → useRef() hors composant.
    • <Suspense fallback={<Loader />}> autour de tout useGLTF / useTexture.
    • dpr={[1, 2]} sur Canvas — jamais 3x (mobile trop lent).
    • dispose() géométries + matériaux dans le cleanup useEffect.
    • > 100 objets identiques → <Instances> ou InstancedMesh, jamais N mesh individuels.

━━ LUMIÈRES & ENVIRONNEMENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Recette standard :
    <ambientLight intensity={0.4} />
    <directionalLight position={[5, 8, 5]} intensity={1.2} castShadow
      shadow-mapSize={[2048, 2048]} shadow-camera-far={50} />
    <Environment preset="city" />   {/* ou "sunset" | "studio" | "night" */}

    Ombres sur Canvas : shadows="soft" (drei SoftShadows) ou gl={{ shadowMap: true }}.
    Meshes : castShadow + receiveShadow.

━━ MODÈLES GLB ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    const { scene, animations } = useGLTF('/models/hero.glb')
    const { actions } = useAnimations(animations, scene)
    useEffect(() => { actions['Idle']?.play() }, [actions])

    Normalise la bounding box au chargement :
    useEffect(() => {
      const box = new Box3().setFromObject(scene)
      const center = box.getCenter(new Vector3())
      const size = box.getSize(new Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      scene.position.sub(center)
      scene.scale.setScalar(2 / maxDim)  // normalise à une taille de 2 unités
    }, [scene])

    FOV : 35-50° (camera.fov) — jamais 75° (distorsion).
    <OrbitControls enableZoom={false} enablePan={false} autoRotate autoRotateSpeed={0.5} />

━━ SCROLL STORYTELLING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Option A — drei ScrollControls (scroll dans le Canvas) :
    <ScrollControls pages={5} damping={0.1}>
      <Scroll>  {/* éléments HTML scrollables */} </Scroll>
      <Scroll html> {/* overlay HTML */} </Scroll>
      {/* Dans useFrame : */}
      const scroll = useScroll()
      // scroll.offset 0→1 · scroll.range(start, end) → 0→1 sur une plage
      mesh.rotation.y = scroll.offset * Math.PI * 2
    </ScrollControls>

    Option B — GSAP ScrollTrigger (scroll natif de la page) :
    import { gsap } from 'gsap'
    import { ScrollTrigger } from 'gsap/ScrollTrigger'
    gsap.registerPlugin(ScrollTrigger)
    gsap.to(meshRef.current.rotation, {
      y: Math.PI * 2,
      scrollTrigger: { trigger: '#section', start: 'top center', end: 'bottom center', scrub: 1 }
    })
    → Une seule source de vérité scroll — ne pas mélanger ScrollControls + GSAP.
    → Lenis pour le smooth scroll : new Lenis() → raf loop → ScrollTrigger.update().

━━ SHADERS CUSTOM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    <shaderMaterial
      vertexShader={vertexGLSL}
      fragmentShader={fragmentGLSL}
      uniforms={{
        uTime:  { value: 0 },
        uMouse: { value: new Vector2() },
        uColor: { value: new Color('#6366f1') },
      }}
    />
    // Dans useFrame : material.uniforms.uTime.value = clock.elapsedTime

    Vertex shader de distorsion (survol) :
      uniform vec2 uMouse; uniform float uTime;
      void main() {
        vec3 pos = position;
        float dist = distance(uv, uMouse);
        pos.z += sin(dist * 10.0 - uTime * 2.0) * 0.05 * (1.0 - dist);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
      }

━━ POST-PROCESSING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    <EffectComposer>
      <Bloom luminanceThreshold={0.3} intensity={1.2} mipmapBlur />
      <ChromaticAberration offset={[0.002, 0.002]} />
      <Vignette darkness={0.4} />
      <DepthOfField focusDistance={0.01} focalLength={0.02} bokehScale={3} />
    </EffectComposer>
    → Activer seulement les effets utiles — chaque effet coûte en perf.

━━ PARTICULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    const COUNT = 2000
    const positions = useMemo(() => {
      const arr = new Float32Array(COUNT * 3)
      for (let i = 0; i < COUNT; i++) {
        arr[i * 3]     = (Math.random() - 0.5) * 10
        arr[i * 3 + 1] = (Math.random() - 0.5) * 10
        arr[i * 3 + 2] = (Math.random() - 0.5) * 10
      }
      return arr
    }, [])
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.02} color="#6366f1" sizeAttenuation transparent opacity={0.7} />
    </points>
    // useFrame : pointsRef.current.rotation.y += 0.0005

━━ PERFORMANCE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    • <PerformanceMonitor onDecline={() => setDpr(1)} onIncline={() => setDpr(2)} /> de drei.
    • Textures : useTexture() de drei (cache automatique).
    • KTX2 / Basis pour les grosses textures : BasisTextureLoader.
    • Jamais de console.log dans useFrame — exécuté 60× par seconde.
    • R3F Perf (debug) : pnpm add r3f-perf → <Perf /> dans <Canvas>.
