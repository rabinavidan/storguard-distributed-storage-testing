pipeline {
    agent any

    parameters {
        choice(
            name: 'ENVIRONMENT',
            choices: ['ci', 'local'],
            description: 'Target environment config (maps to config/<env>.yaml)'
        )
        choice(
            name: 'SUITE',
            choices: ['smoke', 'functional', 'resilience', 'all'],
            description: 'Test suite to execute'
        )
        string(
            name: 'FILE_SIZE_MB',
            defaultValue: '1',
            description: 'Generated test file size in MB'
        )
        string(
            name: 'WORKERS',
            defaultValue: '20',
            description: 'Parallel worker count (pytest-xdist -n)'
        )
        booleanParam(
            name: 'ENABLE_RESILIENCE',
            defaultValue: true,
            description: 'Include chaos and resilience test stages'
        )
        booleanParam(
            name: 'PRESERVE_ON_FAILURE',
            defaultValue: false,
            description: 'Keep cluster alive after failure for manual debugging'
        )
    }

    environment {
        VENV            = '.venv'
        ALLURE_RESULTS  = 'allure-results'
        CONFIG_FILE     = "config/${params.ENVIRONMENT}.yaml"
        MINIO_ROOT_USER = credentials('minio-root-user')
        MINIO_ROOT_PASS = credentials('minio-root-password')
    }

    stages {

        // ── 1. Checkout ────────────────────────────────────────────────────────
        stage('1. Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_REVISION = sh(
                        script: 'git rev-parse --short HEAD',
                        returnStdout: true
                    ).trim()
                    echo "Revision: ${env.GIT_REVISION} | Environment: ${params.ENVIRONMENT}"
                }
            }
        }

        // ── 2. Environment ─────────────────────────────────────────────────────
        stage('2. Environment') {
            steps {
                sh """
                    python3.12 -m venv ${VENV}
                    ${VENV}/bin/pip install --quiet --upgrade pip
                    ${VENV}/bin/pip install --quiet -e ".[dev]"
                """
            }
            post {
                failure {
                    archiveArtifacts artifacts: 'pip-*.log', allowEmptyArchive: true
                }
            }
        }

        // ── 3. Quality ─────────────────────────────────────────────────────────
        stage('3. Quality') {
            parallel {
                stage('Ruff') {
                    steps {
                        sh "${VENV}/bin/ruff check storguard/ tests/"
                    }
                }
                stage('Format') {
                    steps {
                        sh "${VENV}/bin/black --check storguard/ tests/"
                    }
                }
                stage('Types') {
                    steps {
                        sh "${VENV}/bin/mypy storguard/"
                    }
                }
            }
            post {
                failure {
                    archiveArtifacts artifacts: 'ruff-*.txt,mypy-*.txt', allowEmptyArchive: true
                }
            }
        }

        // ── 4. Unit ────────────────────────────────────────────────────────────
        stage('4. Unit') {
            steps {
                sh """
                    mkdir -p test-results
                    ${VENV}/bin/pytest tests/unit/ \
                        --junit-xml=test-results/unit.xml \
                        -v --tb=short
                """
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'test-results/unit.xml'
                }
            }
        }

        // ── 5. Deploy ──────────────────────────────────────────────────────────
        stage('5. Deploy') {
            steps {
                sh """
                    cd infrastructure
                    docker compose --profile storage up -d
                    DEADLINE_SECONDS=120 ./scripts/wait-for-health.sh
                """
            }
            post {
                failure {
                    sh 'docker compose -f infrastructure/docker-compose.yml --profile storage logs --tail=50'
                }
            }
        }

        // ── 6. Smoke ───────────────────────────────────────────────────────────
        stage('6. Smoke') {
            steps {
                sh """
                    ${VENV}/bin/pytest tests/ -m smoke \
                        --alluredir=${ALLURE_RESULTS} \
                        --timeout=300 \
                        -v --tb=short
                """
            }
        }

        // ── 7. Functional ──────────────────────────────────────────────────────
        stage('7. Functional') {
            steps {
                sh """
                    ${VENV}/bin/pytest tests/ -m "functional or integrity" \
                        --alluredir=${ALLURE_RESULTS} \
                        -n ${params.WORKERS} \
                        --timeout=120 \
                        -v --tb=short
                """
            }
        }

        // ── 8. Chaos ───────────────────────────────────────────────────────────
        stage('8. Chaos') {
            when {
                expression { return params.ENABLE_RESILIENCE }
            }
            steps {
                sh """
                    ${VENV}/bin/pytest tests/ -m resilience \
                        --alluredir=${ALLURE_RESULTS} \
                        --timeout=300 \
                        -v --tb=short
                """
            }
        }

        // ── 9. Gate ────────────────────────────────────────────────────────────
        stage('9. Gate') {
            steps {
                sh """
                    ${VENV}/bin/storguard gate evaluate \
                        --config=${CONFIG_FILE} \
                        --results=${ALLURE_RESULTS}
                """
            }
        }

        // ── 10. Publish ────────────────────────────────────────────────────────
        stage('10. Publish') {
            steps {
                allure includeProperties: false, jdk: '', results: [[path: "${ALLURE_RESULTS}"]]
                archiveArtifacts(
                    artifacts: "${ALLURE_RESULTS}/**,test-results/**",
                    fingerprint: true,
                    allowEmptyArchive: true
                )
            }
        }
    }

    // ── 11. Cleanup ────────────────────────────────────────────────────────────
    post {
        always {
            script {
                if (params.PRESERVE_ON_FAILURE && currentBuild.result == 'FAILURE') {
                    echo "[storguard] PRESERVE_ON_FAILURE=true — skipping cluster teardown for debugging."
                } else {
                    sh """
                        cd infrastructure
                        docker compose --profile storage down || true
                    """
                }
            }
            allure includeProperties: false, jdk: '', results: [[path: "${ALLURE_RESULTS}"]]
            cleanWs()
        }
    }
}
