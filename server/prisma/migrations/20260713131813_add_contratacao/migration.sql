-- CreateTable
CREATE TABLE "Contratacao" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "codigoContabilidade" TEXT,
    "processo" TEXT,
    "nup" TEXT,
    "tipoCompra" TEXT,
    "modalidade" TEXT,
    "criterioJulgamento" TEXT,
    "situacaoControle" TEXT,
    "unidadeCompradora" TEXT,
    "objetoCompra" TEXT,
    "criadoEm" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "atualizadoEm" DATETIME NOT NULL
);
