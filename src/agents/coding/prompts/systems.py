"""C / C++ stack prompt."""

SYSTEMS_PROMPT = """\
━━ STACK DÉTECTÉ : C / C++ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   > 2 fichiers sources → CMake obligatoire :
     mkdir build && cmake -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build
   ≤ 2 fichiers → Makefile suffit.

FLAGS DE COMPILATION :
   Dev     → -Wall -Wextra -Werror -g -fsanitize=address,undefined
   Release → -O2 (ou -O3 si benchmarké) -DNDEBUG

MÉMOIRE :
   • AddressSanitizer + UBSan : -fsanitize=address,undefined (dev TOUJOURS).
   • valgrind --leak-check=full --error-exitcode=1 (CI).
   • C++ ≥ 17 : unique_ptr / shared_ptr, RAII, std::span — pas de new/delete raw.
   • C : toujours free() chaque malloc(), vérifier les retours NULL.

TESTS :
   C++  → Catch2 ou Google Test (gtest/gmock).
   C    → Unity ou CMocka.
   Cible séparée dans CMakeLists.txt : add_executable(tests ...) + enable_testing().

MODERNE C++ (≥ 17) :
   • std::optional, std::variant, std::string_view, structured bindings.
   • constexpr / consteval pour le calcul compile-time.
   • Pas d'exceptions dans le code embarqué ou de perf critique — utiliser std::expected (C++23) ou codes d'erreur.

VÉRIFICATION :
   cmake --build build && ctest --test-dir build --output-on-failure
   ou : make && ./tests
"""
